"""Anwesenheit (Zuhause / Abwesend / Urlaub) und Heizsaison (Automatisch / Winter / Sommer)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .const import PRESENCE_OPTIONS, SEASON_OPTIONS
from .coordinator import HeatingCoordinator
from .entity import HubEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([PresenceSelect(entry.runtime_data), SeasonSelect(entry.runtime_data)])


class PresenceSelect(HubEntity, SelectEntity):
    _platform = "select"
    _attr_options = PRESENCE_OPTIONS
    _attr_icon = "mdi:home-account"

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "presence")

    @property
    def current_option(self) -> str:
        return self.coordinator.presence

    async def async_select_option(self, option: str) -> None:
        self.coordinator.presence = option
        for z in self.coordinator.zones.values():
            z.override = None  # von Hand verstellte Temperaturen gelten nur bis zum Anwesenheitswechsel
            z.controller.last_plan_ts = None
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()


class SeasonSelect(HubEntity, SelectEntity):
    """Automatisch: Heizgrenze (24-h-Mittel außen) entscheidet. Sommer: Ventile zu, Lernen pausiert."""

    _platform = "select"
    _attr_options = SEASON_OPTIONS
    _attr_icon = "mdi:sun-snowflake-variant"

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "season")

    @property
    def current_option(self) -> str:
        return self.coordinator.season

    async def async_select_option(self, option: str) -> None:
        self.coordinator.season = option
        for z in self.coordinator.zones.values():
            z.controller.last_plan_ts = None
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()
