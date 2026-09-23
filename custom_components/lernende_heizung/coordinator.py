"""Zentrale Steuerung: liest Sensoren, lernt, plant, stellt Ventile – alle 5 Minuten.

Ereignisse (Fenster auf/zu, Sollwertänderung) lösen sofort einen Regeltakt aus.
Rechenintensives (Optimierung) läuft im Executor, nicht im Event-Loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA,
    CONF_AWAY,
    CONF_COMFORT,
    CONF_ECO_DELTA,
    CONF_HEATING_LIMIT,
    CONF_OUTDOOR,
    CONF_RAD_KW,
    CONF_SCHEDULE,
    CONF_SUN,
    CONF_SUPPLY,
    CONF_SUPPLY_ZONE,
    CONF_TEMP,
    CONF_TEMP2,
    CONF_TRVS,
    CONF_WEATHER,
    CONF_WINDOWS,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONF_ZONES,
    CYCLE_S,
    DEFAULT_AWAY,
    DEFAULT_COMFORT,
    DEFAULT_ECO_DELTA,
    DEFAULT_HEATING_LIMIT,
    DEFAULT_SCHEDULE,
    DOMAIN,
    PARAM_REFRESH_S,
    PRESENCE_AWAY,
    PRESENCE_HOME,
    PRESENCE_VACATION,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_SCHEDULE,
    REPLAN_S,
    STORE_SAVE_DELAY_S,
    STORE_VERSION,
    WINDOW_LEARN_PAUSE_S,
)
from .core.actuator import ValveGate
from .core.controller import (
    REASON_OFF,
    Decision,
    Target,
    ZoneController,
)
from .core.learning import ZoneLearner
from .core.model import HeatingCurve, Inputs, ZoneParams, effective_valve, heating_power_kw, steady_heat_demand
from .core.schedule import ScheduleError, WeekSchedule
from .core.signals import OutdoorFusion, RoomSensorFilter, SunModel, SupplyLearner
from .trv import TrvActuator

_LOGGER = logging.getLogger(__name__)

REASON_SUMMER = "sommer"
REASON_OBSERVE = "beobachten"
FROST_C = 7.0


def _num(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id:
        return None
    st = hass.states.get(entity_id)
    if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        return None
    try:
        v = float(st.state)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def prior_from_config(z: dict) -> ZoneParams:
    """Grobe Startwerte aus Heizkörper-Nennleistung und Fläche (in der Simulation getestet)."""
    area = float(z.get(CONF_AREA) or 15.0)
    kw = float(z.get(CONF_RAD_KW) or 1.5)
    c = max(0.2, 0.05 * area)
    return ZoneParams(h=(kw / c,) * 3, c_eff_kwh_per_k=c)


@dataclass
class Zone:
    """Laufzeitzustand einer Zone."""

    cfg: dict
    schedule: WeekSchedule
    controller: ZoneController
    learner: ZoneLearner
    gate: ValveGate = field(default_factory=ValveGate)
    filt: RoomSensorFilter = field(default_factory=RoomSensorFilter)
    trvs: list[TrvActuator] = field(default_factory=list)
    active: bool = False
    preset: str = PRESET_SCHEDULE
    hvac_off: bool = False
    manual: float | None = None  # Handbetrieb (HVAC heat) – feste Temperatur
    override: float | None = None  # Temporäre Änderung im Zeitplanbetrieb
    override_until: float | None = None
    window_open: bool = False
    temp: float | None = None
    valve_pct: int = 0  # von uns gestellt
    valve_obs: float | None = None  # beobachtet (Beobachtungsmodus, z. B. BT regelt)
    last_open_ts: float = 0.0
    decision: Decision | None = None
    energy_kwh: float = 0.0
    params_ts: float = 0.0
    controlled: bool = False
    saving_pct: float | None = None
    saving_ts: float = 0.0
    last_ext_temp: float | None = None

    @property
    def zid(self) -> str:
        return self.cfg[CONF_ZONE_ID]

    @property
    def name(self) -> str:
        return self.cfg[CONF_ZONE_NAME]

    @property
    def comfort(self) -> float:
        return float(self.cfg.get(CONF_COMFORT, DEFAULT_COMFORT))

    @property
    def eco(self) -> float:
        return self.comfort - float(self.cfg.get(CONF_ECO_DELTA, DEFAULT_ECO_DELTA))

    @property
    def away(self) -> float:
        return float(self.cfg.get(CONF_AWAY, DEFAULT_AWAY))


class HeatingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Eine Instanz je Konfigurationseintrag (= Wohnung)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=CYCLE_S), config_entry=entry)
        self.entry = entry
        self.store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.master_on = True
        self.presence = PRESENCE_HOME
        self.return_at: datetime | None = None
        self.fusion = OutdoorFusion()
        self.sun = SunModel(hass.config.latitude, hass.config.longitude)
        self.supply = SupplyLearner()
        self.t_out: float | None = None
        self.t_out_mean24: float | None = None
        self.sun_now: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.sun_ghi: float = 0.0
        self.forecast: list[tuple[float, float | None, float | None]] = []  # (ts, temp, cloud)
        self.forecast_ts = 0.0
        self._clear_now = 0.5
        self.zones: dict[str, Zone] = {}
        self._unsubs: list = []
        self._last_ts: float | None = None
        self._build_zones()

    # ------------------------------------------------------------------ Aufbau
    @property
    def opts(self) -> dict:
        return {**self.entry.data, **self.entry.options}

    def _build_zones(self) -> None:
        for zc in self.opts.get(CONF_ZONES, []):
            try:
                sched = WeekSchedule.parse(zc.get(CONF_SCHEDULE) or DEFAULT_SCHEDULE)
            except ScheduleError:
                sched = WeekSchedule.parse(DEFAULT_SCHEDULE)
            prior = prior_from_config(zc)
            z = Zone(zc, sched, ZoneController(prior), ZoneLearner(prior))
            z.trvs = [TrvActuator(self.hass, e) for e in zc.get(CONF_TRVS, [])]
            self.zones[zc[CONF_ZONE_ID]] = z

    async def async_setup(self) -> None:
        raw = await self.store.async_load() or {}
        self._restore(raw)
        for z in self.zones.values():
            for t in z.trvs:
                t.resolve()
        watch = []
        for z in self.zones.values():
            watch += list(z.cfg.get(CONF_WINDOWS, []))
        if watch:
            self._unsubs.append(async_track_state_change_event(self.hass, watch, self._on_window))

    async def async_shutdown(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        await self.store.async_save(self._export())
        await super().async_shutdown()

    @callback
    def _on_window(self, _event: Event) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------ Persistenz
    def _export(self) -> dict:
        return {
            "master_on": self.master_on,
            "presence": self.presence,
            "return_at": self.return_at.isoformat() if self.return_at else None,
            "fusion": self.fusion.export(),
            "supply": self.supply.export(),
            "sun_scale": self.sun.scale,
            "sun_n": self.sun.n,
            "t_out_mean24": self.t_out_mean24,
            "zones": {
                zid: {
                    "active": z.active, "preset": z.preset, "hvac_off": z.hvac_off, "manual": z.manual,
                    "energy_kwh": z.energy_kwh, "learner": z.learner.export(), "controller": z.controller.export(),
                    "filter_offset": z.filt.offset, "filter_n": z.filt.n,
                }
                for zid, z in self.zones.items()
            },
        }

    def _restore(self, raw: dict) -> None:
        self.master_on = bool(raw.get("master_on", True))
        if raw.get("presence") in (PRESENCE_HOME, PRESENCE_AWAY, PRESENCE_VACATION):
            self.presence = raw["presence"]
        if raw.get("return_at"):
            self.return_at = dt_util.parse_datetime(raw["return_at"])
        self.fusion.restore(raw.get("fusion", {}))
        self.supply.restore(raw.get("supply", {}))
        self.sun.scale = float(raw.get("sun_scale", 1.0))
        self.sun.n = int(raw.get("sun_n", 0))
        self.t_out_mean24 = raw.get("t_out_mean24")
        for zid, zr in (raw.get("zones") or {}).items():
            z = self.zones.get(zid)
            if z is None:
                continue
            z.active = bool(zr.get("active", False))
            z.preset = zr.get("preset", PRESET_SCHEDULE)
            z.hvac_off = bool(zr.get("hvac_off", False))
            z.manual = zr.get("manual")
            z.energy_kwh = float(zr.get("energy_kwh", 0.0))
            z.learner.restore(zr.get("learner", {}))
            z.controller.restore(zr.get("controller", {}))
            z.controller.params = z.learner.params()
            z.filt.offset = float(zr.get("filter_offset", 0.0))
            z.filt.n = int(zr.get("filter_n", 0))

    def schedule_save(self) -> None:
        self.store.async_delay_save(self._export, STORE_SAVE_DELAY_S)

    # ------------------------------------------------------------------ Sollwerte
    def target_at(self, z: Zone, ts: float) -> Target:
        if z.hvac_off:
            return Target(FROST_C, False)
        if self.presence == PRESENCE_AWAY:
            return Target(z.away, False)
        if self.presence == PRESENCE_VACATION and self.return_at and ts < self.return_at.timestamp():
            return Target(z.away, False)
        if z.manual is not None:
            return Target(z.manual, True)
        if z.preset == PRESET_COMFORT:
            return Target(z.comfort, True)
        if z.preset == PRESET_ECO:
            return Target(z.eco, False)
        if z.preset == PRESET_AWAY:
            return Target(z.away, False)
        if z.override is not None and z.override_until and ts < z.override_until:
            return Target(z.override, True)
        local = dt_util.as_local(dt_util.utc_from_timestamp(ts))
        return Target(z.comfort, True) if z.schedule.is_comfort(local) else Target(z.eco, False)

    def set_override(self, z: Zone, temp: float) -> None:
        """Temporäre Sollwertänderung im Zeitplanbetrieb – bis zum nächsten Zeitplanwechsel."""
        now = dt_util.now()
        nxt = z.schedule.next_change(now)
        z.override = temp
        z.override_until = (nxt or now + timedelta(hours=4)).timestamp()

    # ------------------------------------------------------------------ Vorhersagen
    async def _refresh_forecast(self, now_ts: float) -> None:
        weather = self.opts.get(CONF_WEATHER)
        if not weather or now_ts - self.forecast_ts < 3600:
            return
        self.forecast_ts = now_ts
        try:
            resp = await self.hass.services.async_call(
                "weather", "get_forecasts", {"entity_id": weather, "type": "hourly"}, blocking=True, return_response=True
            )
        except Exception as err:  # noqa: BLE001 – Wetterdienst optional
            _LOGGER.debug("Wettervorhersage nicht verfügbar: %s", err)
            return
        items = ((resp or {}).get(weather) or {}).get("forecast") or []
        fc = []
        for it in items:
            d = dt_util.parse_datetime(str(it.get("datetime", "")))
            if d is None:
                continue
            t = it.get("temperature")
            cc = it.get("cloud_coverage")
            fc.append((d.timestamp(), float(t) if t is not None else None, float(cc) if cc is not None else None))
        self.forecast = sorted(fc)

    def _fc_at(self, ts: float, idx: int) -> float | None:
        if not self.forecast:
            return None
        prev = None
        for f in self.forecast:
            if f[idx] is None:
                continue
            if f[0] >= ts:
                if prev is None:
                    return f[idx]
                w = (ts - prev[0]) / max(1.0, f[0] - prev[0])
                return prev[idx] + w * (f[idx] - prev[idx])
            prev = f
        return prev[idx] if prev else None

    def t_out_at(self, now_ts: float):
        cur = self.t_out if self.t_out is not None else 5.0
        fc_now = self._fc_at(now_ts, 1)
        offset = (cur - fc_now) if fc_now is not None else 0.0

        def f(ts: float) -> float:
            v = self._fc_at(ts, 1)
            if v is None:
                return cur
            decay = math.exp(-max(0.0, ts - now_ts) / (6 * 3600))
            return v + offset * decay
        return f

    def sun_at(self, now_ts: float):
        k_now = self._clear_now

        def f(ts: float) -> tuple[float, float, float]:
            cc = self._fc_at(ts, 2)
            k_fc = 1 - 0.75 * (min(1.0, max(0.0, cc / 100)) if cc is not None else 0.6) ** 3.4
            w = min(1.0, max(0.0, (ts - now_ts) / 7200))  # 2 h: gemessene Klarheit → Vorhersage
            return self.sun.facades(ts, (1 - w) * k_now + w * k_fc)
        return f

    # ------------------------------------------------------------------ Regeltakt
    async def _async_update_data(self) -> dict[str, Any]:
        now_ts = time.time()
        local = dt_util.now()
        opts = self.opts
        await self._refresh_forecast(now_ts)

        # Außen
        weather_t = None
        wid = opts.get(CONF_WEATHER)
        if wid and (wst := self.hass.states.get(wid)) is not None:
            wt = wst.attributes.get("temperature")
            weather_t = float(wt) if isinstance(wt, (int, float)) else None
        self.t_out = self.fusion.update(local.hour, weather_t, _num(self.hass, opts.get(CONF_OUTDOOR)))
        if self.t_out is not None:
            self.t_out_mean24 = self.t_out if self.t_out_mean24 is None else self.t_out_mean24 + (self.t_out - self.t_out_mean24) / 288
        # Sonne (Fassaden Ost/Süd/West)
        ghi_meas = self.sun.ghi_from_lux(_num(self.hass, opts.get(CONF_SUN)))
        self._clear_now = self.sun.clearness(now_ts, ghi_meas, self._fc_at(now_ts, 2))
        self.sun_now = self.sun.facades(now_ts, self._clear_now)
        self.sun_ghi = ghi_meas if ghi_meas is not None else self.sun.ghi(now_ts, self._clear_now)
        # Urlaub vorbei → wieder zuhause
        if self.presence == PRESENCE_VACATION and self.return_at and now_ts > self.return_at.timestamp() + 3600:
            self.presence = PRESENCE_HOME

        # Raumtemperaturen (gefiltert)
        for z in self.zones.values():
            prim = _num(self.hass, z.cfg.get(CONF_TEMP))
            sec = _num(self.hass, z.cfg.get(CONF_TEMP2))
            z.temp = z.filt.update(now_ts, prim, sec)
            z.window_open = any(
                (st := self.hass.states.get(w)) is not None and st.state == STATE_ON for w in z.cfg.get(CONF_WINDOWS, [])
            )

        # Vorlauf (Rohrfühler am Heizkörper der gewählten Zone)
        supply_t = _num(self.hass, opts.get(CONF_SUPPLY))
        sz = self.zones.get(opts.get(CONF_SUPPLY_ZONE) or "")
        if supply_t is not None and sz is not None:
            self.supply.update(now_ts, supply_t, self.t_out, sz.valve_pct / 100)
        curve = HeatingCurve()
        if self.supply.n >= 30:
            curve = HeatingCurve(tvl_at_m10=self.supply.supply(-10), tvl_at_p15=self.supply.supply(15))

        summer = (
            self.t_out_mean24 is not None
            and self.t_out_mean24 > float(opts.get(CONF_HEATING_LIMIT, DEFAULT_HEATING_LIMIT))
        )
        dt_h = 0.0 if self._last_ts is None else min(1.0, (now_ts - self._last_ts) / 3600)
        self._last_ts = now_ts

        temps = {zid: z.temp for zid, z in self.zones.items() if z.temp is not None}
        for z in self.zones.values():
            others = [v for k, v in temps.items() if k != z.zid]
            t_nbr = sum(others) / len(others) if others else None
            x = Inputs(t_out=self.t_out if self.t_out is not None else 5.0, t_nbr=t_nbr, sun=self.sun_now)
            z.controller.curve = curve
            z.learner.curve = curve
            controlling = self.master_on and z.active
            if controlling:
                valve_frac: float | None = z.valve_pct / 100
            else:
                # Beobachtungsmodus: Stellung ablesen, die der TRV (bzw. BT) gerade fährt
                obs = [v for t in z.trvs if (v := t.observed_valve()) is not None]
                valve_frac = sum(obs) / len(obs) if obs else None
                z.valve_obs = valve_frac
            if valve_frac is not None and valve_frac > 0:
                z.last_open_ts = now_ts
            # Lernen (auch im Beobachtungsmodus, sofern die Ventilstellung bekannt ist)
            if z.window_open:
                z.learner.block(now_ts + WINDOW_LEARN_PAUSE_S)
            if valve_frac is not None:
                z.learner.add(now_ts, z.temp, x, valve_frac)
            else:
                z.learner.block(now_ts + CYCLE_S)
            valve_frac = valve_frac or 0.0
            if now_ts - z.params_ts >= PARAM_REFRESH_S:
                z.controller.params = z.learner.params()
                z.params_ts = now_ts
            if z.temp is not None:
                z.controller.observe(now_ts, z.temp, x, effective_valve(valve_frac, z.controller.params.valve_exp))
            z.energy_kwh += heating_power_kw(z.controller.params, z.controller.state) * dt_h if z.controller.state else 0.0

            if summer and not z.window_open and (z.temp is None or z.temp > FROST_C):
                dec = Decision(0.0, 0.0, REASON_SUMMER)
                if controlling and self._exercise_due(z, now_ts, local):
                    dec = Decision(1.0, 1.0, REASON_SUMMER)  # Ventil einmal durchbewegen (gegen Festsitzen)
            else:
                tgt = lambda ts, z=z: self.target_at(z, ts)  # noqa: E731
                dec = await self.hass.async_add_executor_job(
                    lambda: z.controller.decide(
                        now_ts, z.temp, x, tgt, self.t_out_at(now_ts), self.sun_at(now_ts),
                        window_open=z.window_open, replan_s=REPLAN_S,
                    )
                )
                if z.hvac_off and dec.reason not in ("frostschutz", "fenster"):
                    dec = Decision(0.0, 0.0, REASON_OFF)
            if not controlling:
                dec = Decision(dec.u_eff, dec.valve, REASON_OBSERVE if self.master_on else REASON_OFF, dec.plan, dec.disturbance)
            z.decision = dec
            await self._actuate(z, dec, now_ts, controlling)
            await self._update_saving(z, now_ts, x)

        self.schedule_save()
        return {"ts": now_ts}

    @staticmethod
    def _exercise_due(z: Zone, now_ts: float, local: datetime) -> bool:
        """Sonntags 11 Uhr, wenn das Ventil seit über einer Woche zu war."""
        return local.weekday() == 6 and local.hour == 11 and local.minute < 10 and now_ts - z.last_open_ts > 7 * 86400

    async def _actuate(self, z: Zone, dec: Decision, now_ts: float, controlling: bool) -> None:
        if not controlling:
            if z.controlled:
                for t in z.trvs:
                    try:
                        await t.release(z.comfort)
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("%s: TRV %s freigeben fehlgeschlagen: %s", z.name, t.climate_id, err)
                z.controlled = False
                z.gate = ValveGate()
            z.valve_pct = 0
            return
        want = int(round(100 * dec.valve))
        force = not z.controlled or dec.reason in ("fenster", "frostschutz")
        sent = z.gate.decide(now_ts, want, force=force)
        for t in z.trvs:
            try:
                if not z.controlled:
                    await t.take_control()
                if sent is not None:
                    await t.set_valve(sent)
                if z.temp is not None and (z.last_ext_temp is None or abs(z.temp - z.last_ext_temp) >= 0.3):
                    await t.set_room_temperature(z.temp)
            except Exception as err:  # noqa: BLE001 – ein TRV darf die anderen nicht blockieren
                _LOGGER.warning("%s: TRV %s nicht erreichbar: %s", z.name, t.climate_id, err)
        if z.temp is not None and (z.last_ext_temp is None or abs(z.temp - z.last_ext_temp) >= 0.3):
            z.last_ext_temp = z.temp
        z.controlled = True
        if sent is not None:
            z.valve_pct = sent

    async def _update_saving(self, z: Zone, now_ts: float, x: Inputs) -> None:
        """Stündlich: geschätzte Einsparung des Zeitplans gegenüber Dauerkomfort (nächste 12 h)."""
        if now_ts - z.saving_ts < 3600 or z.controller.state is None or z.decision is None or z.decision.plan is None:
            return
        z.saving_ts = now_ts
        import copy  # noqa: PLC0415

        def calc() -> float | None:
            c = copy.deepcopy(z.controller)
            c.z_prev = None
            comfort = c.make_plan(now_ts, x, lambda ts: Target(z.comfort, True), self.t_out_at(now_ts), self.sun_at(now_ts))
            plan = z.decision.plan
            e_c = float(sum(comfort.u))
            e_s = float(sum(plan.u))
            return None if e_c <= 1e-6 else max(0.0, 100 * (1 - e_s / e_c))

        z.saving_pct = await self.hass.async_add_executor_job(calc)

    # ------------------------------------------------------------------ Kennzahlen für Entities
    def zone_power_w(self, z: Zone) -> float:
        return 1000 * heating_power_kw(z.controller.params, z.controller.state) if z.controller.state else 0.0

    def zone_demand_w(self, z: Zone) -> float | None:
        if self.t_out is None:
            return None
        tgt = self.target_at(z, time.time())
        return 1000 * steady_heat_demand(z.controller.params, tgt.setpoint, self.t_out) * z.controller.params.c_eff_kwh_per_k

    def estimated_supply(self) -> float | None:
        if self.t_out is None:
            return None
        if self.supply.n >= 30:
            return self.supply.supply(self.t_out)
        return HeatingCurve().supply(self.t_out)
