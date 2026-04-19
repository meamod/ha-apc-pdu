"""Config flow for APC PDU."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_SNMP_USERNAME,
    CONF_AUTH_PROTOCOL,
    CONF_AUTH_KEY,
    CONF_PRIV_PROTOCOL,
    CONF_PRIV_KEY,
    CONF_OUTLET_COUNT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_OUTLET_COUNT,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    AUTH_PROTOCOLS,
    PRIV_PROTOCOLS,
)

_LOGGER = logging.getLogger(__name__)

# NOTE: .snmp is NOT imported here at module level — importing pysnmp triggers
# blocking file I/O (MIB loading) which HA's event-loop monitor flags.  Instead
# we import APCPDUClient lazily inside _validate_connection.  By the time a user
# submits the form pysnmp is already in sys.modules (loaded by __init__.py during
# setup), so the lazy import is a zero-cost cache look-up on subsequent calls.

STEP_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=""): str,
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(int, vol.Range(min=1, max=65535)),
        vol.Required(CONF_SNMP_USERNAME): str,
        vol.Required(CONF_AUTH_PROTOCOL, default="SHA"): vol.In(AUTH_PROTOCOLS),
        vol.Optional(CONF_AUTH_KEY, default=""): str,
        vol.Required(CONF_PRIV_PROTOCOL, default="AES-128"): vol.In(PRIV_PROTOCOLS),
        vol.Optional(CONF_PRIV_KEY, default=""): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=MIN_SCAN_INTERVAL, max=300)
        ),
    }
)


def _validate_credentials(data: dict) -> dict[str, str]:
    """Return a dict of field-level errors for missing auth/priv keys."""
    errors: dict[str, str] = {}
    if data.get(CONF_AUTH_PROTOCOL, "none") != "none" and not data.get(CONF_AUTH_KEY, "").strip():
        errors[CONF_AUTH_KEY] = "auth_key_required"
    if data.get(CONF_PRIV_PROTOCOL, "none") != "none" and not data.get(CONF_PRIV_KEY, "").strip():
        errors[CONF_PRIV_KEY] = "priv_key_required"
    return errors


async def _validate_connection(data: dict) -> str:
    """Try to read outlet 1 to verify SNMPv3 credentials and connectivity.

    Returns the PDU's configured name (rPDUIdentName) on success, or an empty
    string if the name OID is not available.  Raises on connection failure.
    """
    from .snmp import APCPDUClient  # noqa: PLC0415  (lazy — see module comment)

    _LOGGER.debug(
        "Validating connection to %s:%s as user '%s' (auth=%s, priv=%s)",
        data[CONF_HOST],
        data[CONF_PORT],
        data[CONF_SNMP_USERNAME],
        data[CONF_AUTH_PROTOCOL],
        data[CONF_PRIV_PROTOCOL],
    )
    client = APCPDUClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_SNMP_USERNAME],
        auth_protocol=data[CONF_AUTH_PROTOCOL],
        auth_key=data.get(CONF_AUTH_KEY, ""),
        priv_protocol=data[CONF_PRIV_PROTOCOL],
        priv_key=data.get(CONF_PRIV_KEY, ""),
    )
    state = await client.get_outlet_state(1)
    _LOGGER.debug("Connection validated — outlet 1 state: %s", "on" if state else "off")
    pdu_name = await client.get_pdu_name()
    _LOGGER.debug("PDU name from device: %r", pdu_name)
    return pdu_name


class APCPDUConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for APC PDU."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> APCPDUOptionsFlow:
        """Return the options flow handler."""
        return APCPDUOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate auth/priv key presence before attempting a connection.
            errors = _validate_credentials(user_input)
            if not errors:
                try:
                    pdu_name = await _validate_connection(user_input)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Connection validation failed")
                    errors["base"] = "cannot_connect"
                else:
                    # Use the name the user typed; fall back to the PDU's own
                    # configured name; then fall back to a sensible default.
                    name = user_input.get(CONF_NAME, "").strip() or pdu_name or "APC PDU"
                    return self.async_create_entry(
                        title=name,
                        data={**user_input, CONF_NAME: name},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )


class APCPDUOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to edit poll interval and outlet count after setup."""

    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        # Prefer options (previously saved) then fall back to original setup data.
        entry = self.config_entry
        current_outlet_count = entry.options.get(CONF_OUTLET_COUNT, 0)
        current_scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_OUTLET_COUNT, default=current_outlet_count): vol.All(
                        int, vol.Range(min=0, max=24)
                    ),
                    vol.Optional(CONF_SCAN_INTERVAL, default=current_scan_interval): vol.All(
                        int, vol.Range(min=MIN_SCAN_INTERVAL, max=300)
                    ),
                }
            ),
        )
