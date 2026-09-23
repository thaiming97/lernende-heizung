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
from .coordinator import HeatingCoordinator, Zone
from .entity import ZoneEntity


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    add(ZoneClimate(c, z) for z in c.zones.values())


class ZoneClimate(ZoneEntity, ClimateEntity):
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
        return HVACMode.HEAT if self.zone.manual is not None else HVACMode.AUTO

    @property
    def hvac_action(self) -> HVACAction:
        if self.zone.hvac_off:
            return HVACAction.OFF
        return HVACAction.HEATING if self.zone.valve_pct > 0 else HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        return self.zone.preset

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        z = self.zone
        d = z.decision
        attrs: dict[str, Any] = {"grund": d.reason if d else None, "ventil": z.valve_pct, "aktiv": z.active}
        if z.override is not None and z.override_until and time.time() < z.override_until:
            attrs["uebersteuert_bis"] = time.strftime("%H:%M", time.localtime(z.override_until))
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
            z.manual = self.coordinator.target_at(z, time.time()).setpoint if z.manual is None else z.manual
        elif hvac_mode == HVACMode.AUTO:
            z.manual = None
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
        if z.manual is not None:
            z.manual = float(temp)
        else:
            self.coordinator.set_override(z, float(temp))
        await self._changed()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self.zone.preset = preset_mode
        self.zone.override = None
        await self._changed()
