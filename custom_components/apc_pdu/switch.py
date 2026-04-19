"""Switch platform — one entity per PDU outlet."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import APCPDUCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one switch entity per outlet for this PDU."""
    coordinator: APCPDUCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        APCPDUOutletSwitch(coordinator, outlet)
        for outlet in range(1, coordinator.outlet_count + 1)
    )


class APCPDUOutletSwitch(CoordinatorEntity[APCPDUCoordinator], SwitchEntity):
    """Represents a single switchable outlet on an APC PDU."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:power-socket"

    def __init__(self, coordinator: APCPDUCoordinator, outlet: int) -> None:
        super().__init__(coordinator)
        self._outlet = outlet
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_outlet_{outlet}"
        # Use the name from the PDU if set; fall back to "Outlet N"
        pdu_name = coordinator.outlet_names.get(outlet, "").strip()
        self._attr_name = pdu_name if pdu_name else f"Outlet {outlet}"

    @property
    def available(self) -> bool:
        """Return False when the coordinator failed its last poll."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self._outlet in self.coordinator.data
        )

    @property
    def is_on(self) -> bool:
        """Return True if outlet is on."""
        return bool((self.coordinator.data or {}).get(self._outlet, False))

    async def async_turn_on(self, **kwargs) -> None:
        """Send immediateOn and update HA state optimistically.

        No immediate re-poll after the SET — the PDU needs a moment to apply
        the change, and firing async_request_refresh() straight away causes the
        mobile app to read the old state over WebSocket and snap back to Off.
        The regular coordinator poll will confirm the real state within the
        configured poll interval.
        """
        await self.coordinator.client.set_outlet(self._outlet, True)
        self.coordinator.data[self._outlet] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Send immediateOff and update HA state optimistically.

        Same reasoning as async_turn_on — no immediate re-poll.
        """
        await self.coordinator.client.set_outlet(self._outlet, False)
        self.coordinator.data[self._outlet] = False
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Group all outlets under one device entry per PDU."""
        return self.coordinator.device_info
