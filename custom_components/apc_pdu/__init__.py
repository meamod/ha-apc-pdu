"""APC PDU integration — SNMPv3 outlet control."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_SNMP_USERNAME,
    CONF_AUTH_PROTOCOL,
    CONF_AUTH_KEY,
    CONF_PRIV_PROTOCOL,
    CONF_PRIV_KEY,
    CONF_OUTLET_COUNT,
    CONF_SCAN_INTERVAL,
    DEFAULT_OUTLET_COUNT,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import APCPDUCoordinator
from .snmp import APCPDUClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.SENSOR]


def _get_option(entry: ConfigEntry, key: str, default):
    """Read a value from options first, falling back to data then a default."""
    return entry.options.get(key, entry.data.get(key, default))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an APC PDU from a config entry."""
    client = APCPDUClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_SNMP_USERNAME],
        auth_protocol=entry.data[CONF_AUTH_PROTOCOL],
        auth_key=entry.data.get(CONF_AUTH_KEY, ""),
        priv_protocol=entry.data[CONF_PRIV_PROTOCOL],
        priv_key=entry.data.get(CONF_PRIV_KEY, ""),
    )

    scan_interval = _get_option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    # Determine outlet count: manual options override (> 0) takes priority,
    # otherwise auto-detect from the PDU, falling back to the default.
    # Guard against None — HA stores None when the user unticks the optional
    # field checkbox, which would cause a TypeError on the comparison below.
    manual_count = int(_get_option(entry, CONF_OUTLET_COUNT, 0) or 0)
    if manual_count > 0:
        outlet_count = manual_count
        _LOGGER.debug("Using manual outlet count override: %s", outlet_count)
    else:
        try:
            detected = await client.get_num_outlets()
            if detected:
                outlet_count = detected
                _LOGGER.debug("Auto-detected %s outlets from PDU", outlet_count)
            else:
                outlet_count = DEFAULT_OUTLET_COUNT
                _LOGGER.warning(
                    "Could not auto-detect outlet count from %s — using default %s",
                    entry.data[CONF_HOST], DEFAULT_OUTLET_COUNT,
                )
        except Exception:  # noqa: BLE001
            outlet_count = DEFAULT_OUTLET_COUNT
            _LOGGER.warning(
                "Error auto-detecting outlet count from %s — using default %s",
                entry.data[CONF_HOST], DEFAULT_OUTLET_COUNT,
            )

    coordinator = APCPDUCoordinator(hass, client, outlet_count, scan_interval)

    # Fetch outlet names once at setup — not re-polled on every state update.
    # Gracefully fall back to "Outlet N" labels if the PDU doesn't support the
    # name OID or if the request times out.
    try:
        coordinator.outlet_names = await client.get_outlet_names(outlet_count)
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Could not read outlet names from %s — falling back to 'Outlet N' labels",
            entry.data[CONF_HOST],
        )
        coordinator.outlet_names = {}

    # Fetch PDU identity strings once at setup for DeviceInfo population.
    try:
        coordinator.device_ident = await client.get_device_ident()
        _LOGGER.debug("PDU identity: %s", coordinator.device_ident)
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Could not read identity info from %s — device panel will show defaults",
            entry.data[CONF_HOST],
        )
        coordinator.device_ident = {}

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the entry whenever the user saves new options.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.client.close()
    return unload_ok
