"""Basisklassen für Entities (Geräte: „Lernende Heizung" + je Zone ein Gerät)."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, VERSION
from .coordinator import HeatingCoordinator, Zone

# Sprechende, sprachunabhängige Entity-IDs mit Endung _lh (lernende Heizung)
OBJECT_IDS = {
    "master": "regelung", "presence": "anwesenheit", "season": "heizsaison", "heating_season": "heizperiode", "return_at": "rueckkehr", "outdoor": "aussentemperatur",
    "supply": "vorlauf", "sun": "sonne", "active": "aktiv", "window": "fenster", "preheat": "vorheizen",
    "valve": "ventil", "power": "heizleistung", "energy": "heizenergie", "demand": "waermebedarf",
    "forecast_1h": "temperatur_1h", "forecast_3h": "temperatur_3h", "preheat_start": "vorheizstart",
    "status": "status", "saving": "einsparung", "learning": "lernfortschritt", "model_error": "modellfehler",
    "time_constant": "zeitkonstante", "heat_gain": "heizwirkung", "heat_loss": "waermeverlust", "disturbance": "stoerwaerme",
    "base_gain": "grundwaerme", "explain": "erklaerung", "problem": "problem", "reset_learning": "lernen_zuruecksetzen",
}


def lh_object_id(key: str | None, zid: str | None = None) -> str:
    parts = [p for p in (zid, OBJECT_IDS.get(key or "", key)) if p]
    return "_".join(parts) + "_lh"


class HubEntity(CoordinatorEntity[HeatingCoordinator]):
    _attr_has_entity_name = True
    _platform: str = ""

    def __init__(self, coordinator: HeatingCoordinator, key: str) -> None:
        super().__init__(coordinator)
        if self._platform:
            self.entity_id = f"{self._platform}.{lh_object_id(key)}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)}, name=NAME, manufacturer="Lernende Heizung", sw_version=VERSION
        )


class ZoneEntity(CoordinatorEntity[HeatingCoordinator]):
    _attr_has_entity_name = True
    _platform: str = ""

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone, key: str | None) -> None:
        super().__init__(coordinator)
        self.zone = zone
        if self._platform:
            self.entity_id = f"{self._platform}.{lh_object_id(key, zone.zid)}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone.zid}_{key or 'climate'}"
        if key:
            self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{zone.zid}")},
            name=zone.name,
            manufacturer="Lernende Heizung",
            model="Zone",
        )
