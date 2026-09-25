"""Fenster offen, Vorheizen aktiv und Problem (je Zone), Heizperiode (Wohnung)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .coordinator import HeatingCoordinator, Zone
from .entity import HubEntity, ZoneEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    ents: list[BinarySensorEntity] = [HeatingSeasonSensor(c)]
    for z in c.zones.values():
        ents += [WindowSensor(c, z), PreheatSensor(c, z), ProblemSensor(c, z)]
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


class HeatingSeasonSensor(HubEntity, BinarySensorEntity):
    """An = es wird geheizt und gelernt (Winter bzw. unter der Heizgrenze)."""

    _platform = "binary_sensor"
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "heating_season")

    @property
    def is_on(self) -> bool:
        return self.coordinator.heating_season


class ProblemSensor(ZoneEntity, BinarySensorEntity):
    """An, wenn etwas nicht stimmt (Sensor/Thermostat weg, Befehl nicht angekommen, Sicherheitsbetrieb,
    Kessel kalt); die Liste steht im Attribut „probleme“."""

    _platform = "binary_sensor"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone) -> None:
        super().__init__(coordinator, zone, "problem")

    @property
    def is_on(self) -> bool:
        return bool(self.zone.problems)

    @property
    def extra_state_attributes(self) -> dict:
        return {"probleme": list(self.zone.problems)}
