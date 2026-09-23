"""Fenster offen (je Zone, zusammengefasst) und Vorheizen aktiv."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .coordinator import HeatingCoordinator, Zone
from .entity import ZoneEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    ents = []
    for z in c.zones.values():
        ents += [WindowSensor(c, z), PreheatSensor(c, z)]
    add(ents)


class WindowSensor(ZoneEntity, BinarySensorEntity):
    _platform = "binary_sensor"
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone) -> None:
        super().__init__(coordinator, zone, "window")

    @property
    def is_on(self) -> bool:
        return self.zone.window_open


class PreheatSensor(ZoneEntity, BinarySensorEntity):
    _platform = "binary_sensor"
    _attr_icon = "mdi:clock-fast"

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone) -> None:
        super().__init__(coordinator, zone, "preheat")

    @property
    def is_on(self) -> bool:
        d = self.zone.decision
        return bool(d and d.reason == "vorheizen")
