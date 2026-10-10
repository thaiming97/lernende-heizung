"""Klima-Entity je Zone: Automatik (Zeitplan), Manuell (feste Temperatur), Aus; Presets."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .const import PRESET_AWAY, PRESET_COMFORT, PRESET_ECO, PRESET_SCHEDULE
from .coordinator import HeatingCoordinator, Zone, _hhmm
from .entity import ZoneEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    add(ZoneClimate(c, z) for z in c.zones.values())


class ZoneClimate(ZoneEntity, ClimateEntity):
    _platform = "climate"
    _attr_name = None
    _attr_translation_key = "zone"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_SCHEDULE, PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = 7
    _attr_max_temp = 28
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone) -> None:
        super().__init__(coordinator, zone, None)

    @property
    def current_temperature(self) -> float | None:
        return None if self.zone.temp is None else round(self.zone.temp, 2)

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.target_at(self.zone, time.time()).setpoint

    @property
    def hvac_mode(self) -> HVACMode:
        if self.zone.hvac_off:
            return HVACMode.OFF
        return HVACMode.HEAT if self.coordinator.manual_active(self.zone, time.time()) else HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction:
        if self.zone.hvac_off:
            return HVACAction.OFF
        # tatsächliche Stellung – im Beobachtungsmodus die abgelesene
        return HVACAction.HEATING if (self.zone.valve_frac or 0.0) > 0.02 else HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        return self.coordinator.preset_at(self.zone, time.time())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        z = self.zone
        d = z.decision
        attrs: dict[str, Any] = {"grund": d.reason if d else None, "ventil": z.valve_pct, "aktiv": z.active}
        if self.coordinator.sofi_active(z):
            attrs["sofi"] = True
        # von Hand eingestellt (Temperatur, „Heizen“ oder Preset) – gilt bis Mitternacht
        until = self.coordinator.hand_until(z, time.time())
        attrs["manuell"] = until is not None
        if until is not None:
            attrs["manuell_bis"] = _hhmm(until)
        if d and d.plan is not None:
            attrs["vorhersage"] = [round(float(t), 2) for t in d.plan.t_pred[3::4][:12]]  # stündlich, 12 h
        return attrs

    async def _changed(self) -> None:
        self.zone.controller.last_plan_ts = None  # sofort neu planen
        self.coordinator.schedule_save()
        await self.coordinator.async_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        z = self.zone
        z.hvac_off = hvac_mode == HVACMode.OFF
        if hvac_mode == HVACMode.HEAT:
            now = time.time()
            temp = z.manual if self.coordinator.manual_active(z, now) else self.coordinator.target_at(z, now).setpoint
            self.coordinator.set_manual(z, temp)
        elif hvac_mode == HVACMode.AUTO:
            self.coordinator.set_manual(z, None)
        z.override = None  # neue Betriebsart gilt sofort (Übersteuerung hat sonst Vorrang)
        await self._changed()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        z = self.zone
        if self.coordinator.manual_active(z, time.time()):
            self.coordinator.set_manual(z, float(temp))
            z.override = None
        else:
            self.coordinator.set_override(z, float(temp))
        await self._changed()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self.coordinator.set_preset(self.zone, preset_mode)
        self.zone.override = None
        self.coordinator.set_manual(self.zone, None)  # Presets gelten nur in Automatik – „Heizen“ endet damit
        await self._changed()
