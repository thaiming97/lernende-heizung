"""Knopf „Gelerntes zurücksetzen“: Wärmemodell aller Zonen verwerfen und neu lernen."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .coordinator import HeatingCoordinator
from .entity import HubEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([ResetLearningButton(entry.runtime_data)])


class ResetLearningButton(HubEntity, ButtonEntity):
    _platform = "button"
    _attr_icon = "mdi:restart"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "reset_learning")

    async def async_press(self) -> None:
        self.coordinator.reset_learning()
        await self.coordinator.async_refresh()
