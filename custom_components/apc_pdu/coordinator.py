"""DataUpdateCoordinator for APC PDU outlet states and load sensors."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .snmp import APCPDUClient

_LOGGER = logging.getLogger(__name__)


class APCPDUCoordinator(DataUpdateCoordinator[dict[int, bool]]):
    """Poll all outlet states and PDU load metrics from one PDU on a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: APCPDUClient,
        entry: ConfigEntry,
        outlet_count: int,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.config_entry = entry
        self.outlet_count = outlet_count
        # Populated once at setup by async_setup_entry; not re-polled on every update.
        self.outlet_names: dict[int, str] = {}
        # Identity strings fetched once at setup from rPDUIdent OIDs.
        self.device_ident: dict[str, str] = {}
        # Load metrics — updated on every coordinator refresh alongside outlet states.
        # None means the PDU did not return a value (unsupported or SNMP error).
        self.load_amps: float | None = None
        self.load_state: int | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return DeviceInfo shared by all entities on this PDU."""
        ident = self.device_ident
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=self.config_entry.data[CONF_NAME],
            manufacturer="APC by Schneider Electric",
            model=ident.get("model") or "AP7920",
            serial_number=ident.get("serial") or None,
            sw_version=ident.get("firmware") or None,
        )

    async def _async_update_data(self) -> dict[int, bool]:
        try:
            outlet_states = await self.client.get_all_outlet_states(self.outlet_count)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with PDU: {err}") from err

        # Load metrics are fetched best-effort — a failure here does not prevent
        # outlet state updates from succeeding.
        try:
            self.load_amps, self.load_state = await self.client.get_load_metrics()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not read load metrics from PDU — will retry next poll")
            self.load_amps = None
            self.load_state = None

        return outlet_states
