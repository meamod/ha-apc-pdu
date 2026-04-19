"""DataUpdateCoordinator for APC PDU outlet states."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
from .snmp import APCPDUClient

_LOGGER = logging.getLogger(__name__)


class APCPDUCoordinator(DataUpdateCoordinator[dict[int, bool]]):
    """Poll all outlet states from one PDU on a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: APCPDUClient,
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
        self.outlet_count = outlet_count
        # Populated once at setup by async_setup_entry; not re-polled on every update.
        self.outlet_names: dict[int, str] = {}

    async def _async_update_data(self) -> dict[int, bool]:
        try:
            return await self.client.get_all_outlet_states(self.outlet_count)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with PDU: {err}") from err
