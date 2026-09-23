"""Rückkehrzeit für den Urlaubsmodus."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HeatingConfigEntry
from .coordinator import HeatingCoordinator
from .entity import HubEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([ReturnDateTime(entry.runtime_data)])


class ReturnDateTime(HubEntity, DateTimeEntity):
    _attr_icon = "mdi:airplane-landing"

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "return_at")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.return_at

    async def async_set_value(self, value: datetime) -> None:
        self.coordinator.return_at = dt_util.as_utc(value)
        for z in self.coordinator.zones.values():
            z.controller.last_plan_ts = None
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()
