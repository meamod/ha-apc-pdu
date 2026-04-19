"""Sensor platform — PDU-level current draw and load status."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOAD_STATE_MAP
from .coordinator import APCPDUCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create load and identity sensors for this PDU."""
    coordinator: APCPDUCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        APCPDUCurrentSensor(coordinator, entry),
        APCPDULoadStateSensor(coordinator, entry),
        APCPDUIdentSensor(coordinator, entry, "PDU Name", "name", "mdi:tag-text"),
        APCPDUIdentSensor(coordinator, entry, "Manufacture Date", "manufacture_date", "mdi:calendar"),
        APCPDUIdentSensor(coordinator, entry, "Number of Outlets", "num_outlets", "mdi:counter"),
    ])


class _APCPDUBaseSensor(CoordinatorEntity[APCPDUCoordinator], SensorEntity):
    """Shared base for PDU-level sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: APCPDUCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to the same device as the outlet switches."""
        ident = self.coordinator.device_ident
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.data[CONF_NAME],
            manufacturer="APC by Schneider Electric",
            model=ident.get("model") or "AP7920",
            serial_number=ident.get("serial") or None,
            sw_version=ident.get("firmware") or None,
        )


class APCPDUCurrentSensor(_APCPDUBaseSensor):
    """Reports the total current draw of the PDU in Amps."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:current-ac"

    def __init__(self, coordinator: APCPDUCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_load_amps"
        self._attr_name = "Current"

    @property
    def available(self) -> bool:
        """Unavailable if the coordinator failed or the PDU doesn't support this OID."""
        return self.coordinator.last_update_success and self.coordinator.load_amps is not None

    @property
    def native_value(self) -> float | None:
        """Return the current draw in Amps."""
        return self.coordinator.load_amps


class APCPDULoadStateSensor(_APCPDUBaseSensor):
    """Reports the PDU load state (Normal, Near Overload, Overload, Low Load)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:gauge"
    _attr_options = list(LOAD_STATE_MAP.values())

    def __init__(self, coordinator: APCPDUCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_load_state"
        self._attr_name = "Load Status"

    @property
    def available(self) -> bool:
        """Unavailable if the coordinator failed or the PDU doesn't support this OID."""
        return self.coordinator.last_update_success and self.coordinator.load_state is not None

    @property
    def native_value(self) -> str | None:
        """Return the human-readable load state string."""
        return LOAD_STATE_MAP.get(self.coordinator.load_state)


class APCPDUIdentSensor(_APCPDUBaseSensor):
    """Exposes a single PDU identity string (name, manufacture date) as a diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: APCPDUCoordinator,
        entry: ConfigEntry,
        name: str,
        ident_key: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._ident_key = ident_key
        self._attr_unique_id = f"{entry.entry_id}_ident_{ident_key}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        """Unavailable when the identity value is empty."""
        return bool(self.coordinator.device_ident.get(self._ident_key))

    @property
    def native_value(self) -> str | None:
        """Return the identity string."""
        return self.coordinator.device_ident.get(self._ident_key) or None
