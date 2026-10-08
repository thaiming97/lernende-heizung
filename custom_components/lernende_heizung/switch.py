"""Schalter: Regelung gesamt an/aus, je Zone „aktiv regeln" (aus = nur beobachten und lernen)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .coordinator import HeatingCoordinator, Zone
from .entity import HubEntity, ZoneEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    add([MasterSwitch(c), SofiSwitch(c), *(ZoneActiveSwitch(c, z) for z in c.zones.values())])


class MasterSwitch(HubEntity, SwitchEntity):
    _platform = "switch"
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "master")

    @property
    def is_on(self) -> bool:
        return self.coordinator.master_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.master_on = True
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.master_on = False
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()


class SofiSwitch(HubEntity, SwitchEntity):
    """Sofi ist da: Räume mit eingestellter Sofi-Temperatur werden wärmer (auch bei „Abwesend“/„Urlaub“)."""

    _platform = "switch"
    _attr_icon = "mdi:account-heart"

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "sofi")

    @property
    def is_on(self) -> bool:
        return self.coordinator.sofi_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.set_sofi(True)
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.set_sofi(False)
        await self.coordinator.async_refresh()


class ZoneActiveSwitch(ZoneEntity, SwitchEntity):
    _platform = "switch"
    _attr_icon = "mdi:thermostat-auto"

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone) -> None:
        super().__init__(coordinator, zone, "active")

    @property
    def is_on(self) -> bool:
        return self.zone.active

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.zone.active = True
        self.zone.controller.last_plan_ts = None
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.zone.active = False
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()
