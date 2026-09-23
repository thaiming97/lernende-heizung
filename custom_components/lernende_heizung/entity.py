"""Basisklassen für Entities (Geräte: „Lernende Heizung" + je Zone ein Gerät)."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, VERSION
from .coordinator import HeatingCoordinator, Zone


class HubEntity(CoordinatorEntity[HeatingCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HeatingCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)}, name=NAME, manufacturer="Lernende Heizung", sw_version=VERSION
        )


class ZoneEntity(CoordinatorEntity[HeatingCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone, key: str | None) -> None:
        super().__init__(coordinator)
        self.zone = zone
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone.zid}_{key or 'climate'}"
        if key:
            self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{zone.zid}")},
            name=zone.name,
            manufacturer="Lernende Heizung",
            model="Zone",
        )
