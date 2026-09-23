"""Statistik- und Diagnosesensoren (werden in HA langfristig gespeichert)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import time

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HeatingConfigEntry
from .coordinator import HeatingCoordinator, Zone
from .entity import HubEntity, ZoneEntity

REASONS = ["komfort", "absenkung", "vorheizen", "fenster", "frostschutz", "aus", "rueckfall", "kein_sensor", "sommer", "beobachten"]


@dataclass(frozen=True, kw_only=True)
class ZoneSensorDesc(SensorEntityDescription):
    value: Callable[[HeatingCoordinator, Zone], object]


@dataclass(frozen=True, kw_only=True)
class HubSensorDesc(SensorEntityDescription):
    value: Callable[[HeatingCoordinator], object]


def _plan_temp(z: Zone, hours: float):
    d = z.decision
    if d is None or d.plan is None:
        return None
    k = int(round(hours / 0.25)) - 1
    return round(float(d.plan.t_pred[min(k, len(d.plan.t_pred) - 1)]), 2)


def _preheat(z: Zone) -> datetime | None:
    d = z.decision
    if d is None or d.plan is None or d.plan.preheat_start_h is None:
        return None
    return dt_util.utc_from_timestamp(time.time() + d.plan.preheat_start_h * 3600)


def _gain_now(c: HeatingCoordinator, z: Zone):
    if c.t_out is None:
        return None
    from .core.model import radiator_factor  # noqa: PLC0415

    p = z.controller.params
    t = z.temp if z.temp is not None else 20.0
    return round(p.heat_gain(c.t_out) * radiator_factor(z.controller.curve.supply(c.t_out), t), 3)


ZONE_SENSORS: tuple[ZoneSensorDesc, ...] = (
    ZoneSensorDesc(key="valve", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
                   icon="mdi:valve", value=lambda c, z: z.valve_pct),
    ZoneSensorDesc(key="power", device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
                   state_class=SensorStateClass.MEASUREMENT, value=lambda c, z: round(c.zone_power_w(z))),
    ZoneSensorDesc(key="energy", device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                   state_class=SensorStateClass.TOTAL_INCREASING, value=lambda c, z: round(z.energy_kwh, 3)),
    ZoneSensorDesc(key="demand", device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
                   state_class=SensorStateClass.MEASUREMENT, value=lambda c, z: None if (v := c.zone_demand_w(z)) is None else round(v)),
    ZoneSensorDesc(key="forecast_1h", device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                   state_class=SensorStateClass.MEASUREMENT, value=lambda c, z: _plan_temp(z, 1)),
    ZoneSensorDesc(key="forecast_3h", device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                   state_class=SensorStateClass.MEASUREMENT, value=lambda c, z: _plan_temp(z, 3)),
    ZoneSensorDesc(key="preheat_start", device_class=SensorDeviceClass.TIMESTAMP, value=lambda c, z: _preheat(z)),
    ZoneSensorDesc(key="status", device_class=SensorDeviceClass.ENUM, options=REASONS,
                   value=lambda c, z: z.decision.reason if z.decision else None),
    ZoneSensorDesc(key="saving", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT, icon="mdi:piggy-bank",
                   value=lambda c, z: None if z.saving_pct is None else round(z.saving_pct, 1)),
    ZoneSensorDesc(key="learning", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
                   entity_category=EntityCategory.DIAGNOSTIC, icon="mdi:school", value=lambda c, z: round(100 * z.learner.progress())),
    ZoneSensorDesc(key="model_error", native_unit_of_measurement="K/h", state_class=SensorStateClass.MEASUREMENT,
                   entity_category=EntityCategory.DIAGNOSTIC, value=lambda c, z: round(z.learner.rmse(), 3)),
    ZoneSensorDesc(key="time_constant", device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.HOURS,
                   state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
                   value=lambda c, z: round(1 / max(z.controller.params.k_ma, 1e-4), 1)),
    ZoneSensorDesc(key="heat_gain", native_unit_of_measurement="K/h", state_class=SensorStateClass.MEASUREMENT,
                   entity_category=EntityCategory.DIAGNOSTIC, value=_gain_now),
    ZoneSensorDesc(key="heat_loss", native_unit_of_measurement="W/K", state_class=SensorStateClass.MEASUREMENT,
                   entity_category=EntityCategory.DIAGNOSTIC,
                   value=lambda c, z: round(1000 * (z.controller.params.k_o + z.controller.params.k_n) * z.controller.params.c_eff_kwh_per_k, 1)),
    ZoneSensorDesc(key="disturbance", native_unit_of_measurement="K/h", state_class=SensorStateClass.MEASUREMENT,
                   entity_category=EntityCategory.DIAGNOSTIC, value=lambda c, z: round(z.controller.d, 3)),
)

HUB_SENSORS: tuple[HubSensorDesc, ...] = (
    HubSensorDesc(key="outdoor", device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                  state_class=SensorStateClass.MEASUREMENT, value=lambda c: None if c.t_out is None else round(c.t_out, 1)),
    HubSensorDesc(key="supply", device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                  state_class=SensorStateClass.MEASUREMENT, value=lambda c: None if (v := c.estimated_supply()) is None else round(v, 1)),
    HubSensorDesc(key="sun", device_class=SensorDeviceClass.IRRADIANCE, native_unit_of_measurement="W/m²",
                  state_class=SensorStateClass.MEASUREMENT, value=lambda c: round(1000 * c.sun_ghi)),
)


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    ents: list[SensorEntity] = [HubSensor(c, d) for d in HUB_SENSORS]
    for z in c.zones.values():
        ents += [ZoneSensor(c, z, d) for d in ZONE_SENSORS]
    add(ents)


class ZoneSensor(ZoneEntity, SensorEntity):
    _platform = "sensor"
    entity_description: ZoneSensorDesc

    def __init__(self, coordinator: HeatingCoordinator, zone: Zone, desc: ZoneSensorDesc) -> None:
        super().__init__(coordinator, zone, desc.key)
        self.entity_description = desc

    @property
    def native_value(self):
        return self.entity_description.value(self.coordinator, self.zone)


class HubSensor(HubEntity, SensorEntity):
    _platform = "sensor"
    entity_description: HubSensorDesc

    def __init__(self, coordinator: HeatingCoordinator, desc: HubSensorDesc) -> None:
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def native_value(self):
        return self.entity_description.value(self.coordinator)
