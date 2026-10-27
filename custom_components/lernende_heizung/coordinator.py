"""Zentrale Steuerung: liest Sensoren, lernt, plant, stellt Ventile – alle 5 Minuten.

Ereignisse (Fenster auf/zu, Sollwertänderung) lösen sofort einen Regeltakt aus.
Rechenintensives (Optimierung) läuft im Executor, nicht im Event-Loop.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
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
    CONF_SOFI,
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
    CONTACT_NOTICE_S,
    CYCLE_S,
    DECISION_LOG_LEN,
    DEFAULT_AWAY,
    DEFAULT_COMFORT,
    DEFAULT_ECO_DELTA,
    DEFAULT_HEATING_LIMIT,
    DEFAULT_SCHEDULE,
    DOMAIN,
    DOORS_NOTICE_S,
    DOORS_SETTLE_S,
    EXT_TEMP_REFRESH_S,
    FALLBACK_MIN_SAMPLES,
    FALLBACK_RMSE,
    HEATING_LIMIT_HYST,
    PARAM_REFRESH_S,
    PRESENCE_AWAY,
    PRESENCE_HOME,
    PRESENCE_VACATION,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_SCHEDULE,
    REPLAN_S,
    SEASON_AUTO,
    SEASON_OPTIONS,
    SEASON_SUMMER,
    SEASON_WINTER,
    SENSOR_STALE_S,
    STARTUP_GRACE_S,
    VACATION_REPLAN_S,
    SUPPLY_STALE_S,
    STORE_SAVE_DELAY_S,
    STORE_SAVE_INTERVAL_S,
    STORE_VERSION,
    SUN_STALE_S,
    WINDOW_DELAY_S,
    WINDOW_LEARN_PAUSE_S,
    WINDOW_RESUME_S,
    WINDOW_SETTLE_S,
)
from .core.actuator import ValveGate
from .core.controller import (
    REASON_COMFORT,
    REASON_NO_SENSOR,
    REASON_OFF,
    REASON_PREHEAT,
    Decision,
    Target,
    ZoneController,
)
from .core.learning import ZoneLearner
from .core.explain import Situation, explain
from .core.model import (
    HeatingCurve,
    Inputs,
    ZoneParams,
    effective_valve,
    heating_power_kw,
    steady_heat_demand,
    valve_from_effective,
)
from .core.schedule import ScheduleError, WeekSchedule
from .core.signals import OutdoorFusion, RoomSensorFilter, SunModel, SupplyLearner
from .core.vacation import plan_vacation, worth_it
from .trv import TrvActuator

_LOGGER = logging.getLogger(__name__)

REASON_SUMMER = "sommer"
REASON_OBSERVE = "beobachten"
FROST_C = 7.0
SUN_DIRECT_KW = 0.05  # kW/m² direkte Sonne auf einer Fassade → Sonnenspitzen am Raumsensor möglich
TRV_NOTICE_S = 3600  # so lange bleibt „Thermostat stand auf Aus“ in der Problemliste
# Warum das Lernen gerade pausiert (Sensor „Erklärung“)
PAUSE_WINDOW = "Fenster war gerade offen"
PAUSE_SEASON = "Heizperiode hat gerade erst begonnen"
PAUSE_VALVE = "Ventilstellung war gerade unsicher"
PAUSE_COLD_PIPE = "Rohr kalt trotz offenem Ventil – unklar, ob Wärme ankommt"
PAUSE_DOORS = "Türen offen oder gerade erst zu"


def _num(hass: HomeAssistant, entity_id: str | None, max_age_s: float | None = None) -> float | None:
    """Zahlenwert einer Entity; mit max_age_s gilt ein Sensor ohne Meldung als ausgefallen
    (Zigbee-Sensoren behalten bei leerer Batterie oft einfach den letzten Wert)."""
    if not entity_id:
        return None
    st = hass.states.get(entity_id)
    if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        return None
    if max_age_s is not None:
        seen = getattr(st, "last_reported", None) or st.last_updated
        if (dt_util.utcnow() - seen).total_seconds() > max_age_s:
            return None
    try:
        v = float(st.state)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _local_hour(ts: float) -> int:
    return dt_util.as_local(dt_util.utc_from_timestamp(ts)).hour


def _hhmm(ts: float) -> str:
    return dt_util.as_local(dt_util.utc_from_timestamp(ts)).strftime("%H:%M")


_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _when(ts: float, now_ts: float) -> str:
    """Uhrzeit, ab 24 h voraus mit Wochentag (Urlaub über mehrere Tage)."""
    if ts - now_ts < 24 * 3600:
        return _hhmm(ts)
    loc = dt_util.as_local(dt_util.utc_from_timestamp(ts))
    return f"{_WEEKDAYS[loc.weekday()]} {loc.strftime('%H:%M')}"


def _ts_or(v: Any, default: float) -> float:
    return float(v) if isinstance(v, (int, float)) else default


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
    # Von Hand gesetzt (Preset, „Heizen“, Temperatur) gilt bis Mitternacht, danach wieder Automatik.
    # Bewusst ohne Ende: Zone „Aus“.
    preset: str = PRESET_SCHEDULE
    preset_until: float | None = None
    hvac_off: bool = False
    manual: float | None = None  # Handbetrieb (HVAC heat) – feste Temperatur
    manual_until: float | None = None
    override: float | None = None  # Temperatur von Hand in Automatik
    override_until: float | None = None
    window_open: bool = False  # mindestens WINDOW_DELAY_S offen
    window_closed_ts: float | None = None  # danach bleibt das Ventil WINDOW_RESUME_S zu
    block_reason: str | None = None  # warum das Lernen zuletzt pausiert wurde
    temp: float | None = None
    valve_pct: int = 0  # von uns gestellt
    valve_obs: float | None = None  # beobachtet (Beobachtungsmodus, z. B. BT regelt)
    last_open_ts: float = 0.0
    last_window_ts: float = 0.0
    decision: Decision | None = None
    energy_kwh: float = 0.0
    params_ts: float = 0.0
    controlled: bool = False
    saving_pct: float | None = None
    saving_ts: float = 0.0
    last_ext_temp: float | None = None
    last_ext_ts: float = 0.0
    controlling: bool = False
    vac_preheat_ts: float | None = None  # Urlaub: spätester Start mit voller Leistung
    vac_preheating: bool = False  # Urlaub: Vorheizen für die Rückkehr läuft (ab da gilt der Zeitplan)
    valve_frac: float | None = None  # wirksame Stellung 0..1 (gestellt bzw. beobachtet), None = unbekannt
    primary_missing: bool = False
    info: dict = field(default_factory=dict)  # „was denkt die Regelung" (Sensor Erklärung)
    explanation: str | None = None
    problems: list[str] = field(default_factory=list)
    log: deque = field(default_factory=lambda: deque(maxlen=DECISION_LOG_LEN))  # letzte Entscheidungen (Diagnose)

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
    def eco_delta(self) -> float:
        return float(self.cfg.get(CONF_ECO_DELTA, DEFAULT_ECO_DELTA))

    @property
    def eco(self) -> float:
        return self.comfort - self.eco_delta

    @property
    def sofi_temp(self) -> float | None:
        """Komforttemperatur, wenn Sofi da ist (None = Raum bleibt wie immer)."""
        v = self.cfg.get(CONF_SOFI)
        return None if v is None else float(v)

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
        self.sofi_on = False  # Sofi-Modus: gewählte Räume wärmer (eigene Temperatur je Zone)
        self.doors_open = False  # Schalter „Türen offen“ (Innentüren auf, z. B. für den Saugroboter)
        self.doors_since: float | None = None
        self.doors_last_ts = 0.0  # zuletzt Türen offen – danach noch DOORS_SETTLE_S Lernpause
        self.presence = PRESENCE_HOME
        self.season = SEASON_AUTO
        self.heating_season = True  # Ergebnis aus Heizsaison-Auswahl bzw. Heizgrenze
        self.return_at: datetime | None = None
        # Urlaub mit Rückkehr: einmal entschieden, ob Absenken sich lohnt (None = noch nicht)
        self.vac_key: float | None = None  # Rückkehrzeit, für die entschieden wurde
        self.vac_setback: bool | None = None
        self.vac_frac: float | None = None  # Anteil der Wärme fürs Warmhalten, den das Absenken spart
        self.vac_kwh: float | None = None
        self.vac_ts = 0.0  # letzte Rechnung
        self.fusion = OutdoorFusion()
        self.sun = SunModel(hass.config.latitude, hass.config.longitude)
        self.supply = SupplyLearner()
        self.curve = HeatingCurve()
        self.t_supply: float | None = None  # Vorlauf fürs Modell
        self.supply_shown: float | None = None  # Vorlauf für die Anzeige (Messwert, sobald es einen gibt)
        self.supply_pipe: float | None = None  # Rohwert des Vorlauffühlers (für die Anzeige)
        self.supply_note: str | None = None  # warum der Fühler gerade zählt bzw. nicht
        self.t_out: float | None = None
        self.t_out_mean24: float | None = None
        self.sun_now: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.sun_ghi: float = 0.0
        self.forecast: list[tuple[float, float | None, float | None]] = []  # (ts, temp, cloud)
        self.forecast_ts = 0.0
        self._clear_now = 0.5
        self.zones: dict[str, Zone] = {}
        self._unsubs: list = []
        self._window_timers: set = set()
        self._last_ts: float | None = None
        self._saved_ts = 0.0
        self._start_ts = time.time()
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

    def reset_learning(self) -> None:
        """Gelerntes Wärmeverhalten aller Zonen verwerfen und bei den Startwerten neu beginnen.

        Bleibt erhalten: Abgleich der Sensoren (Außenfühler-Versatz, Sonne, Haupt-/Zweitsensor) und
        die Heizkurve aus dem Vorlauffühler – die hängen nicht davon ab, ob geheizt wurde."""
        for z in self.zones.values():
            prior = prior_from_config(z.cfg)
            z.learner = ZoneLearner(prior)
            z.controller = ZoneController(prior, hour_of=z.controller.hour_of)
            z.params_ts = 0.0
            z.saving_pct = None
        self._update_curve()  # Startwerte an die aktuelle Heizkurve anpassen
        self.schedule_save()
        _LOGGER.info("Gelerntes aller Zonen zurückgesetzt")

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
        for u in [*self._unsubs, *self._window_timers]:
            u()
        self._unsubs.clear()
        self._window_timers.clear()
        await self.store.async_save(self._export())
        await super().async_shutdown()

    @callback
    def _on_window(self, event: Event) -> None:
        self.hass.async_create_task(self.async_request_refresh())
        new = event.data.get("new_state")
        if new is not None and new.state == STATE_ON:
            # zählt erst nach WINDOW_DELAY_S – dann ohne auf den nächsten Regeltakt zu warten prüfen
            def _due(_now: datetime) -> None:
                self._window_timers.discard(cancel)
                self.hass.async_create_task(self.async_request_refresh())

            cancel = async_call_later(self.hass, WINDOW_DELAY_S + 1, callback(_due))
            self._window_timers.add(cancel)

    def set_doors(self, on: bool) -> None:
        """Schalter „Türen offen“ (nur von Hand): solange an (und DOORS_SETTLE_S danach) lernt keine Zone.
        Geregelt wird normal."""
        if on and not self.doors_open:
            self.doors_since = time.time()
        self.doors_open = on
        if not on:
            self.doors_since = None
        self.schedule_save()

    def doors_forgotten(self, now_ts: float) -> bool:
        """Schalter schon lange an – vergessen? (Er geht bewusst nicht von selbst aus.)"""
        return self.doors_open and self.doors_since is not None and now_ts - self.doors_since >= DOORS_NOTICE_S

    def _window_is_open(self, z: Zone, now_ts: float) -> bool:
        """Fenster/Tür gilt erst als offen, wenn sie WINDOW_DELAY_S offen steht (kurz rausgehen zählt nicht)."""
        for w in z.cfg.get(CONF_WINDOWS, []):
            st = self.hass.states.get(w)
            if st is not None and st.state == STATE_ON and now_ts - st.last_changed.timestamp() >= WINDOW_DELAY_S:
                return True
        return False

    @staticmethod
    def _block(z: Zone, until: float, reason: str) -> None:
        if until >= z.learner.blocked_until:
            z.block_reason = reason
        z.learner.block(until)

    # ------------------------------------------------------------------ Persistenz
    def _export(self) -> dict:
        return {
            "master_on": self.master_on,
            "sofi_on": self.sofi_on,
            "doors_open": self.doors_open,
            "doors_since": self.doors_since,
            "doors_last_ts": self.doors_last_ts,
            "presence": self.presence,
            "season": self.season,
            "heating_season": self.heating_season,
            "return_at": self.return_at.isoformat() if self.return_at else None,
            "vacation": {"key": self.vac_key, "setback": self.vac_setback, "frac": self.vac_frac, "kwh": self.vac_kwh},
            "fusion": self.fusion.export(),
            "supply": self.supply.export(),
            "sun_scale": self.sun.scale,
            "sun_n": self.sun.n,
            "t_out_mean24": self.t_out_mean24,
            "zones": {
                zid: {
                    "active": z.active, "preset": z.preset, "preset_until": z.preset_until, "hvac_off": z.hvac_off,
                    "manual": z.manual, "manual_until": z.manual_until,
                    "override": z.override, "override_until": z.override_until,
                    "energy_kwh": z.energy_kwh, "learner": z.learner.export(), "controller": z.controller.export(),
                    "filter_offset": z.filt.offset, "filter_n": z.filt.n,
                    "vac_preheat_ts": z.vac_preheat_ts, "vac_preheating": z.vac_preheating,
                }
                for zid, z in self.zones.items()
            },
        }

    def _restore(self, raw: dict) -> None:
        self.master_on = bool(raw.get("master_on", True))
        self.sofi_on = bool(raw.get("sofi_on", False))
        self.doors_open = bool(raw.get("doors_open", False))
        since, last = raw.get("doors_since"), raw.get("doors_last_ts")
        self.doors_since = float(since) if self.doors_open and isinstance(since, (int, float)) else None
        if self.doors_open and self.doors_since is None:
            self.doors_since = time.time()
        self.doors_last_ts = float(last) if isinstance(last, (int, float)) else 0.0
        if raw.get("presence") in (PRESENCE_HOME, PRESENCE_AWAY, PRESENCE_VACATION):
            self.presence = raw["presence"]
        if raw.get("season") in SEASON_OPTIONS:
            self.season = raw["season"]
        self.heating_season = bool(raw.get("heating_season", True))
        if raw.get("return_at"):
            self.return_at = dt_util.parse_datetime(raw["return_at"])
        vac = raw.get("vacation") or {}
        if self.presence == PRESENCE_VACATION and isinstance(vac.get("key"), (int, float)):
            self.vac_key = float(vac["key"])
            self.vac_setback = vac.get("setback") if isinstance(vac.get("setback"), bool) else None
            self.vac_frac = vac.get("frac") if isinstance(vac.get("frac"), (int, float)) else None
            self.vac_kwh = vac.get("kwh") if isinstance(vac.get("kwh"), (int, float)) else None
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
            # Stände ohne Ende (vor 0.7.1 galt „von Hand“ unbefristet) enden an der nächsten Mitternacht
            end = self.hand_end()
            z.preset = zr.get("preset", PRESET_SCHEDULE)
            if z.preset != PRESET_SCHEDULE:
                z.preset_until = _ts_or(zr.get("preset_until"), end)
            z.hvac_off = bool(zr.get("hvac_off", False))
            man = zr.get("manual")
            if isinstance(man, (int, float)):
                z.manual, z.manual_until = float(man), _ts_or(zr.get("manual_until"), end)
            ov = zr.get("override")
            if isinstance(ov, (int, float)):
                z.override, z.override_until = float(ov), _ts_or(zr.get("override_until"), end)
            z.energy_kwh = float(zr.get("energy_kwh", 0.0))
            z.learner.restore(zr.get("learner", {}))
            z.controller.restore(zr.get("controller", {}))
            z.controller.params = z.learner.params()
            if self.vac_key is not None:
                pt = zr.get("vac_preheat_ts")
                z.vac_preheat_ts = float(pt) if isinstance(pt, (int, float)) else None
                z.vac_preheating = bool(zr.get("vac_preheating", False))
            z.filt.offset = float(zr.get("filter_offset", 0.0))
            z.filt.n = int(zr.get("filter_n", 0))

    def schedule_save(self) -> None:
        self.store.async_delay_save(self._export, STORE_SAVE_DELAY_S)

    # ------------------------------------------------------------------ Sollwerte
    def target_at(self, z: Zone, ts: float) -> Target:
        if z.hvac_off:
            return Target(FROST_C, False)
        # Von Hand verstellte Temperatur gilt bis Mitternacht – auch bei Preset oder Abwesenheit
        if self.override_active(z, ts):
            return Target(z.override, True)
        manual = z.manual if self.manual_active(z, ts) else None
        preset = self.preset_at(z, ts)
        # Sofi da: ihre Räume bleiben warm, auch wenn „Abwesend“/„Urlaub“ eingestellt ist
        sofi = self.sofi_active(z)
        if self.presence == PRESENCE_AWAY and not sofi:
            return Target(z.away, False)
        # Urlaub: Abwesenheitstemperatur bis zur Rückkehr (ohne Rückkehrzeit unbegrenzt); danach gilt wieder
        # der Zeitplan. Mit Rückkehrzeit nur, wenn sich das Absenken lohnt, und nur bis zum Vorheizen
        # (_update_vacation): ab dann gilt der Zeitplan schon jetzt – der Regler heizt mit voller Leistung.
        if (self.presence == PRESENCE_VACATION and not sofi and self.vac_setback is not False and not z.vac_preheating
                and (self.return_at is None or ts < self.return_at.timestamp())):
            return Target(z.away, False)
        if manual is not None:
            return Target(manual, True)
        comfort = self.comfort_of(z)
        eco = comfort - z.eco_delta
        if preset == PRESET_COMFORT:
            return Target(comfort, True)
        if preset == PRESET_ECO:
            return Target(eco, False)
        if preset == PRESET_AWAY:
            return Target(z.away, False)
        local = dt_util.as_local(dt_util.utc_from_timestamp(ts))
        return Target(comfort, True) if z.schedule.is_comfort(local) else Target(eco, False)

    def sofi_active(self, z: Zone) -> bool:
        return self.sofi_on and z.sofi_temp is not None

    def comfort_of(self, z: Zone) -> float:
        """Komforttemperatur jetzt – mit Sofi-Modus die Sofi-Temperatur der Zone."""
        return z.sofi_temp if self.sofi_active(z) and z.sofi_temp is not None else z.comfort

    def set_sofi(self, on: bool) -> None:
        """Sofi-Modus an/aus. Neue Situation: von Hand verstellte Temperaturen ihrer Räume enden (wie beim
        Anwesenheitswechsel), alle Zonen planen sofort neu."""
        self.sofi_on = on
        for z in self.zones.values():
            if z.sofi_temp is not None:
                z.override = None
            z.controller.last_plan_ts = None
        self.schedule_save()

    @staticmethod
    def hand_end() -> float:
        """Ende einer Einstellung von Hand: die nächste Mitternacht (Felix: „bis nachts um 12“)."""
        return dt_util.start_of_local_day(dt_util.now() + timedelta(days=1)).timestamp()

    def set_override(self, z: Zone, temp: float) -> None:
        """Temperatur von Hand in Automatik – gilt bis Mitternacht, auch über Zeitplanwechsel hinweg.
        Früher: bis zum nächsten Zeitplanwechsel bzw. bei Zeitplan „immer“ unbefristet."""
        z.override = temp
        z.override_until = self.hand_end()

    def set_manual(self, z: Zone, temp: float | None) -> None:
        """„Heizen“ mit fester Temperatur bis Mitternacht; None = zurück auf Automatik."""
        z.manual = temp
        z.manual_until = None if temp is None else self.hand_end()

    def set_preset(self, z: Zone, preset: str) -> None:
        z.preset = preset
        z.preset_until = None if preset == PRESET_SCHEDULE else self.hand_end()

    @staticmethod
    def override_active(z: Zone, ts: float) -> bool:
        return z.override is not None and (z.override_until is None or ts < z.override_until)

    @staticmethod
    def manual_active(z: Zone, ts: float) -> bool:
        return z.manual is not None and (z.manual_until is None or ts < z.manual_until)

    @staticmethod
    def preset_at(z: Zone, ts: float) -> str:
        if z.preset != PRESET_SCHEDULE and (z.preset_until is None or ts < z.preset_until):
            return z.preset
        return PRESET_SCHEDULE

    def hand_until(self, z: Zone, ts: float) -> float | None:
        """Bis wann gerade eine Einstellung von Hand gilt (None = Automatik)."""
        if z.hvac_off:
            return None
        ends = []
        if self.override_active(z, ts):
            ends.append(z.override_until)
        if self.manual_active(z, ts):
            ends.append(z.manual_until)
        if self.preset_at(z, ts) != PRESET_SCHEDULE:
            ends.append(z.preset_until)
        if not ends:
            return None
        return None if any(e is None for e in ends) else max(ends)

    def _expire_hand(self, z: Zone, ts: float) -> None:
        """Abgelaufene Einstellungen von Hand löschen – die Zone läuft wieder in Automatik."""
        changed = False
        if z.override is not None and not self.override_active(z, ts):
            z.override = z.override_until = None
            changed = True
        if z.manual is not None and not self.manual_active(z, ts):
            z.manual = z.manual_until = None
            changed = True
        if z.preset != PRESET_SCHEDULE and self.preset_at(z, ts) == PRESET_SCHEDULE:
            z.preset, z.preset_until = PRESET_SCHEDULE, None
            changed = True
        if changed:
            z.controller.last_plan_ts = None
            self.schedule_save()

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
        ghi_meas = self.sun.ghi_from_lux(_num(self.hass, opts.get(CONF_SUN), SUN_STALE_S))
        self._clear_now = self.sun.clearness(now_ts, ghi_meas, self._fc_at(now_ts, 2))
        self.sun_now = self.sun.facades(now_ts, self._clear_now)
        self.sun_ghi = ghi_meas if ghi_meas is not None else self.sun.ghi(now_ts, self._clear_now)
        # Urlaub vorbei → wieder zuhause
        if self.presence == PRESENCE_VACATION and self.return_at and now_ts > self.return_at.timestamp() + 3600:
            self.presence = PRESENCE_HOME
        await self._update_vacation(now_ts)

        # Raumtemperaturen (gefiltert), Fenster, Ventilstellung
        sun_direct = max(self.sun_now) > SUN_DIRECT_KW
        for z in self.zones.values():
            self._expire_hand(z, now_ts)
            was_open = z.window_open
            z.window_open = self._window_is_open(z, now_ts)
            if z.window_open:
                z.last_window_ts = now_ts
                z.window_closed_ts = None
            elif was_open:  # gerade geschlossen (der Fensterkontakt löst sofort einen Takt aus)
                z.last_window_ts = now_ts
                z.window_closed_ts = now_ts
            prim = _num(self.hass, z.cfg.get(CONF_TEMP), SENSOR_STALE_S)
            sec = _num(self.hass, z.cfg.get(CONF_TEMP2), SENSOR_STALE_S)
            z.primary_missing = prim is None
            # Spitzenfilter nur, wenn Sonne auf den Sensor fallen kann – und nicht, während sich der Raum
            # vom Lüften erholt (die Luft wird dann echt schnell wieder warm)
            settling = now_ts - z.last_window_ts < WINDOW_SETTLE_S
            z.temp = z.filt.update(now_ts, prim, sec, sun=sun_direct, settling=settling)
            z.controlling = self.master_on and z.active
            z.valve_frac = self._valve_frac(z, now_ts)

        # Vorlauf: Rohrfühler am Strang der gewählten Zonen – zählt, sobald eines ihrer Ventile offen ist
        # (live 11.10.: nachts nur das Bad offen, Rohr zeigte echte 26 °C, wurde aber verworfen, weil nur
        # Wohnen eingetragen war). Bezug ist der kühlste Raum: Der Fühler hängt in einem davon, und ruhendes
        # Wasser kühlt auf dessen Temperatur ab.
        supply_t = _num(self.hass, opts.get(CONF_SUPPLY), SUPPLY_STALE_S)
        szs = self._supply_zones()
        valves = [z.valve_frac for z in szs]
        known = [v for v in valves if v is not None]
        rooms = [z.temp for z in szs if z.temp is not None]
        # eine Stellung unbekannt und die übrigen zu → unklar, ob Wasser fließt
        if supply_t is not None and known and (len(known) == len(valves) or max(known) >= self.supply.OPEN_MIN):
            self.supply.update(now_ts, supply_t, self.t_out, max(known), t_room=min(rooms) if rooms else None,
                               hour=local.hour)
        self.supply_pipe = supply_t
        self.supply_note = self._supply_note(now_ts, supply_t, szs) if opts.get(CONF_SUPPLY) else None
        self._update_curve()
        t_out_now = self.t_out if self.t_out is not None else 5.0
        measured = self.supply.measured(now_ts)
        # Das Modell nimmt den Messwert erst mit gelernter Heizkurve: Die Startwerte der Heizwirkung passen
        # zur angenommenen Kurve, erst beim Übernehmen der gelernten wird die Heizwirkung umgerechnet.
        # Ausnahme: Kessel kalt – dann kommt ohnehin keine Wärme an.
        use_measured = measured is not None and (
            self.supply.curve_params() is not None or self.supply.heat_missing(now_ts)
        )
        self.t_supply = measured if use_measured else self.curve.supply(t_out_now, local.hour)
        self.supply_shown = measured if measured is not None else self.t_supply

        if self.season == SEASON_SUMMER:
            summer = True
        elif self.season == SEASON_WINTER:
            summer = False
        else:
            # Heizgrenze mit Schaltabstand: erst 0,5 K darüber Sommer, erst 0,5 K darunter wieder Winter
            limit = float(opts.get(CONF_HEATING_LIMIT, DEFAULT_HEATING_LIMIT))
            m = self.t_out_mean24
            if m is None:
                summer = False
            elif self.heating_season:
                summer = m > limit + HEATING_LIMIT_HYST
            else:
                summer = m >= limit - HEATING_LIMIT_HYST
        self.heating_season = not summer
        dt_h = 0.0 if self._last_ts is None else min(1.0, (now_ts - self._last_ts) / 3600)
        self._last_ts = now_ts

        doors = self.doors_open
        if doors:
            self.doors_last_ts = now_ts
        doors_recent = now_ts - self.doors_last_ts < DOORS_SETTLE_S
        temps = {zid: z.temp for zid, z in self.zones.items() if z.temp is not None}
        for z in self.zones.values():
            others = [v for k, v in temps.items() if k != z.zid]
            t_nbr = sum(others) / len(others) if others else None
            x = Inputs(t_out=t_out_now, t_nbr=t_nbr, sun=self.sun_now, t_supply=self.t_supply)
            controlling = z.controlling
            valve_frac = z.valve_frac
            if valve_frac is not None and valve_frac > 0:
                z.last_open_ts = now_ts
            # Lernen (auch im Beobachtungsmodus, sofern die Ventilstellung bekannt ist). Im Sommer
            # pausiert es: offene Fenster, Sommerlüftung und starke Sonne passen nicht zum Winter, und
            # der Zug zum Startwert würde das Gelernte über die Heizkörper langsam vergessen.
            if z.last_window_ts == now_ts:  # offen oder gerade geschlossen
                self._block(z, now_ts + WINDOW_LEARN_PAUSE_S, PAUSE_WINDOW)
            if doors:  # Innentüren offen: Wärme fließt zwischen den Räumen ganz anders als sonst
                self._block(z, now_ts + DOORS_SETTLE_S, PAUSE_DOORS)
            if summer:
                self._block(z, now_ts + CYCLE_S, PAUSE_SEASON)
            elif valve_frac is None:
                self._block(z, now_ts + CYCLE_S, PAUSE_VALVE)
            elif valve_frac > 0.02 and self.supply.pipe_cold(now_ts):
                # Ventil offen, Rohr kalt: kommt Wärme an? Unklar → nicht lernen (sonst wirken die
                # Heizkörper im Modell schwächer, als sie sind)
                self._block(z, now_ts + CYCLE_S, PAUSE_COLD_PIPE)
            if valve_frac is not None:
                z.learner.add(now_ts, z.temp, x, valve_frac)  # in einer Pause: nur Zustände fortschreiben
            valve_frac = valve_frac or 0.0
            if now_ts - z.params_ts >= PARAM_REFRESH_S:
                z.controller.params = z.learner.params()
                z.params_ts = now_ts
            if z.temp is not None:
                # Fenster offen (und kurz danach) bzw. Türen gerade zu: nicht als Störgröße lernen – die wäre
                # nach dem Schließen falsch und klänge erst über Stunden ab
                # Türen noch offen: d führt nach (Modell stimmt dann nicht; eingefrorene Duschwärme hielt am 20.10. das
                # Bad-Ventil zu, 23,3 → 22,7). Eingefroren klingt d ab.
                freeze = now_ts - z.last_window_ts < WINDOW_LEARN_PAUSE_S or (doors_recent and not doors)
                z.controller.observe(now_ts, z.temp, x, effective_valve(valve_frac, z.controller.params.valve_exp), freeze_d=freeze)
            z.energy_kwh += heating_power_kw(z.controller.params, z.controller.state) * dt_h if z.controller.state else 0.0

            if summer and not z.window_open and (z.temp is None or z.temp > FROST_C):
                dec = Decision(0.0, 0.0, REASON_SUMMER)
                if controlling and self._exercise_due(z, now_ts, local):
                    dec = Decision(1.0, 1.0, REASON_SUMMER)  # Ventil einmal durchbewegen (gegen Festsitzen)
            else:
                tgt = lambda ts, z=z: self.target_at(z, ts)  # noqa: E731
                # Modell sagt die Raumtemperatur dauerhaft schlecht voraus → einfacher PI-Regler
                bad_model = z.learner.samples >= FALLBACK_MIN_SAMPLES and z.learner.rmse() > FALLBACK_RMSE
                closed = z.window_open or self._window_wait_until(z, now_ts) is not None
                dec = await self.hass.async_add_executor_job(
                    lambda: z.controller.decide(
                        now_ts, z.temp, x, tgt, self.t_out_at(now_ts), self.sun_at(now_ts),
                        window_open=closed, use_fallback=bad_model, replan_s=REPLAN_S,
                    )
                )
                if z.hvac_off and dec.reason not in ("frostschutz", "fenster"):
                    dec = Decision(0.0, 0.0, REASON_OFF)
                elif dec.reason == REASON_COMFORT and self.vac_preheat_running(z, now_ts):
                    dec = Decision(dec.u_eff, dec.valve, REASON_PREHEAT, dec.plan, dec.disturbance)
            if not controlling:
                dec = Decision(dec.u_eff, dec.valve, REASON_OBSERVE if self.master_on else REASON_OFF, dec.plan, dec.disturbance)
            elif dec.reason == REASON_NO_SENSOR and now_ts - self._start_ts < STARTUP_GRACE_S:
                # Kurz nach dem Start fehlt der Raumsensor meist nur, weil er sich noch nicht gemeldet hat:
                # Ventile so lassen, statt alle auf die Notöffnung zu stellen (live 10.10.: alle auf 12 %)
                z.decision = dec
                self._describe(z, now_ts, summer)
                continue
            # Ende der Fensterpause: sofort stellen, nicht erst nach dem Mindestabstand zwischen Ventilbefehlen
            resume = z.decision is not None and z.decision.reason == "fenster" and dec.reason != "fenster"
            z.decision = dec
            await self._actuate(z, dec, now_ts, controlling, force=resume)
            await self._update_saving(z, now_ts, x)
            self._describe(z, now_ts, summer)

        # Gelerntes in festem Abstand sichern (Absturz, Stromausfall); Bedienung speichert zusätzlich
        if now_ts - self._saved_ts >= STORE_SAVE_INTERVAL_S:
            self._saved_ts = now_ts
            self.store.async_delay_save(self._export, 0)
        return {"ts": now_ts}

    @staticmethod
    def _window_wait_until(z: Zone, now_ts: float) -> float | None:
        """Fenster wieder zu, Ventil bleibt aber noch zu: bis wann? (None = keine Wartezeit)"""
        if z.window_open or z.window_closed_ts is None:
            return None
        until = z.window_closed_ts + WINDOW_RESUME_S
        return until if now_ts < until else None

    def _valve_frac(self, z: Zone, now_ts: float) -> float | None:
        """Ventilstellung 0..1: gestellt (aktiv) bzw. am TRV abgelesen (beobachten); None = unbekannt."""
        if any(not t.available() for t in z.trvs):
            return None  # ein Thermostat nicht erreichbar → wir wissen nicht, was die Zone heizt
        if z.controlling and z.controlled:
            # Kopf aus, Befehl fehlgeschlagen oder nicht übernommen → Stellung unsicher, nicht lernen
            if any(t.uncertain(now_ts) for t in z.trvs):
                return None
            return z.valve_pct / 100
        obs = [v for t in z.trvs if (v := t.observed_valve()) is not None]
        z.valve_obs = sum(obs) / len(obs) if obs else None
        return z.valve_obs

    def _supply_zones(self) -> list[Zone]:
        """Zonen, deren Heizkörper am Strang des Vorlauffühlers hängen (bis 0.8 genau eine, als Text gespeichert)."""
        raw = self.opts.get(CONF_SUPPLY_ZONE) or []
        ids = [raw] if isinstance(raw, str) else list(raw)
        return [self.zones[i] for i in ids if i in self.zones]

    def _supply_note(self, now_ts: float, pipe: float | None, szs: list[Zone]) -> str:
        """Kurz und verständlich: zählt der Vorlauffühler gerade, und wenn nicht, warum?"""
        s = self.supply
        if pipe is None:
            return "Fühler meldet sich nicht"
        if not szs:
            return "keine Zone gewählt (Konfigurieren → Vorlauffühler)"
        if s.heat_alarm(now_ts):
            return "Kessel liefert keine Wärme – Rohr kalt trotz offenem Ventil"
        if s.heat_missing(now_ts):
            return "Rohr kalt trotz offenem Ventil – Kessel liefert gerade kaum Wärme (z. B. Beginn der Nachtabsenkung)"
        if s.pipe_cold(now_ts) and s.n == 0:
            return "zählt nicht – Rohr bleibt kalt trotz offenem Ventil: sitzt der Fühler am Vorlaufrohr?"
        if s.measured(now_ts) is not None:
            if s.curve_params() is None:
                return f"zählt – Heizwasser fließt (Heizkurve wird gelernt: {s.n}/30 Messungen)"
            return "zählt – Heizwasser fließt"
        known = [z.valve_frac for z in szs if z.valve_frac is not None]
        if not known or (len(known) < len(szs) and max(known) < s.OPEN_MIN):
            unknown = ", ".join(z.name for z in szs if z.valve_frac is None)
            return f"zählt nicht – Ventilstellung {unknown} unbekannt"
        if max(known) < s.OPEN_MIN:
            return f"zählt nicht – Ventil {szs[0].name} zu" if len(szs) == 1 else "zählt nicht – alle Ventile am Strang zu"
        if s.open_since is not None and now_ts - s.open_since < 20 * 60:
            return f"zählt gleich – Ventil erst seit {int((now_ts - s.open_since) // 60)} min offen"
        return "zählt nicht – Rohr kaum wärmer als der Raum (fließt kein Heizwasser)"

    def _update_curve(self) -> None:
        """Heizkurve aus dem Vorlauffühler übernehmen (sobald genug gelernt); die Lerner rechnen
        ihre Heizwirkung dabei um, damit das bisher Gelernte gültig bleibt. Ab dann ist der Vorlauf gemessen,
        und die Heizwirkung gilt für alle Außentemperaturen gleich (gekoppelte Anker)."""
        cp = self.supply.curve_params()
        curve = HeatingCurve() if cp is None else HeatingCurve(tvl_at_m10=cp[0], tvl_at_p15=cp[1], hour_offset=cp[2])
        t_ref = self.t_out_mean24 if self.t_out_mean24 is not None else self.t_out
        for z in self.zones.values():
            before = (z.learner.curve_ref, z.learner.coupled)
            z.learner.adopt_curve(curve)  # zuerst: Startwerte passen zur angenommenen Kurve, einmal umrechnen
            if z.learner.coupled != (cp is not None):
                z.learner.set_coupled(cp is not None, t_ref if t_ref is not None else 5.0)
            if (z.learner.curve_ref, z.learner.coupled) != before:
                z.controller.params = z.learner.params()
            z.controller.curve = curve
            if z.controller.hour_of is None:
                z.controller.hour_of = _local_hour
        self.curve = curve

    # ------------------------------------------------------------------ Urlaub
    def _vac_reset(self) -> None:
        self.vac_key = self.vac_setback = self.vac_frac = self.vac_kwh = None
        for z in self.zones.values():
            z.vac_preheat_ts, z.vac_preheating = None, False

    def vac_active(self, now_ts: float) -> bool:
        """Urlaub mit Rückkehrzeit, die noch kommt."""
        return self.presence == PRESENCE_VACATION and self.return_at is not None and now_ts < self.return_at.timestamp()

    def vac_preheat_running(self, z: Zone, now_ts: float) -> bool:
        return self.vac_active(now_ts) and z.vac_preheating

    async def _update_vacation(self, now_ts: float) -> None:
        """Urlaub mit Rückkehrzeit: beim Eintragen der Rückkehr einmal entscheiden, ob sich das Absenken lohnt
        (core.vacation); danach stündlich den spätesten Vorheizstart nachrechnen – mit dem, wie weit die Räume
        wirklich ausgekühlt sind. Ist er erreicht, gilt für die Zone der Zeitplan: volle Leistung bis warm."""
        if self.presence != PRESENCE_VACATION:
            if self.vac_key is not None:
                self._vac_reset()
            return
        if not self.vac_active(now_ts):
            return
        ret = self.return_at.timestamp()  # type: ignore[union-attr]
        new = ret != self.vac_key
        if new or now_ts - self.vac_ts >= VACATION_REPLAN_S:
            zones = [z for z in self.zones.values()
                     if z.controller.state is not None and not z.hvac_off and not self.sofi_active(z) and not z.vac_preheating]
            if zones:
                t_out_at = self.t_out_at(now_ts)
                comfort = {z.zid: self.target_at(z, ret + 60).setpoint for z in zones}

                def calc() -> dict:
                    return {z.zid: plan_vacation(z.controller.params, z.controller.state, self.curve, _local_hour, now_ts,
                                                 ret, comfort[z.zid], z.away, t_out_at) for z in zones}

                plans = await self.hass.async_add_executor_job(calc)
                self.vac_ts = now_ts
                if new:
                    self.vac_key = ret
                    self.vac_setback, self.vac_frac, self.vac_kwh = worth_it(list(plans.values()))
                    _LOGGER.info("Urlaub bis %s: Absenken %s (spart %.0f %% = %.1f kWh)", self.return_at,
                                 "lohnt sich" if self.vac_setback else "lohnt sich nicht", 100 * self.vac_frac, self.vac_kwh)
                    for z in self.zones.values():
                        z.vac_preheating = False
                        z.controller.last_plan_ts = None
                for z in zones:
                    z.vac_preheat_ts = plans[z.zid].preheat_ts
        if self.vac_setback:
            for z in self.zones.values():
                if not z.vac_preheating and z.vac_preheat_ts is not None and now_ts >= z.vac_preheat_ts:
                    z.vac_preheating = True
                    z.controller.last_plan_ts = None

    def next_change(self, z: Zone, now_ts: float) -> tuple[float, float, bool] | None:
        """Nächster Sollwertwechsel in den kommenden 24 h: (Zeit, Sollwert, Komfort?)."""
        cur = self.target_at(z, now_ts)
        start = now_ts - now_ts % 900 + 900
        for k in range(96):
            ts = start + k * 900
            tg = self.target_at(z, ts)
            if tg.setpoint != cur.setpoint or tg.comfort != cur.comfort:
                return ts, tg.setpoint, tg.comfort
        return None

    def _sun_gain(self, z: Zone, now_ts: float, hours: float = 3.0) -> float:
        """Erwärmung durch Sonne in den nächsten Stunden laut Modell (K, ohne Speicherdämpfung)."""
        f = self.sun_at(now_ts)
        g = z.controller.params.g_sun
        return sum(sum(gi * si for gi, si in zip(g, f(now_ts + k * 900))) * 0.25 for k in range(int(hours * 4)))

    def _describe(self, z: Zone, now_ts: float, summer: bool) -> None:
        """Erklärung, Kennzahlen und Probleme einer Zone für die Entities aufbereiten."""
        d = z.decision
        tg = self.target_at(z, now_ts)
        plan = d.plan if d else None
        nxt = self.next_change(z, now_ts)
        t_at_change = None
        if plan is not None and nxt is not None:
            k = int(round((nxt[0] - now_ts) / 900)) - 1
            if 0 <= k < len(plan.t_pred):
                t_at_change = float(plan.t_pred[k])
        preheat_ts = now_ts + plan.preheat_start_h * 3600 if plan is not None and plan.preheat_start_h is not None else None
        # Urlaub mit Rückkehr: lohnt sich das Absenken nicht, sagt die Erklärung das; sonst den spätesten Vorheizstart
        # (der Regler-Plan sieht nur 12 h); beim Vorheizen ist der nächste Wechsel die Rückkehr
        note = None
        if self.vac_active(now_ts) and not self.sofi_active(z) and not z.hvac_off:
            ret = self.return_at.timestamp()  # type: ignore[union-attr]
            if self.vac_setback is False and self.vac_frac is not None:
                note = f"Urlaub: Absenken lohnt sich nicht (spart nur ~{100 * self.vac_frac:.0f} %), bleibt warm"
            elif z.vac_preheating:
                nxt = (ret, tg.setpoint, True)
            elif self.vac_setback and z.vac_preheat_ts is not None and (preheat_ts is None or z.vac_preheat_ts < preheat_ts):
                preheat_ts = z.vac_preheat_ts
        # aktiv geregelt: was gerade gestellt wurde (die abgelesene Stellung hinkt einen Takt hinterher)
        valve_now = z.valve_pct if z.controlling and z.controlled else int(round(100 * (z.valve_frac or 0.0)))
        want = int(round(100 * d.valve)) if d else 0
        paused = None
        if not summer:
            if z.valve_frac is None:
                paused = "Ventilstellung unsicher (Thermostat nicht erreichbar, aus oder Befehl nicht angekommen)"
            elif z.temp is None:
                paused = "kein Raumwert"
            elif not z.window_open and now_ts < z.learner.blocked_until:
                paused = z.block_reason or "kurz pausiert"
        rmse = z.learner.rmse()
        sun3 = self._sun_gain(z, now_ts) if not summer else 0.0
        heat_missing = self.supply.heat_alarm(now_ts) and not summer  # Meldung erst nach ALARM_S
        sit = Situation(
            reason=d.reason if d else "aus", temp=z.temp, setpoint=tg.setpoint, valve_pct=valve_now, want_pct=want,
            fmt_time=lambda ts: _when(ts, now_ts), next_change=nxt, temp_at_change=t_at_change,
            temp_in_1h=float(plan.t_pred[3]) if plan is not None and len(plan.t_pred) > 3 else None,
            preheat_ts=preheat_ts, sun_3h_k=sun3, disturbance=z.controller.d, model_error=rmse, season=self.season,
            t_out_mean24=self.t_out_mean24,
            heating_limit=float(self.opts.get(CONF_HEATING_LIMIT, DEFAULT_HEATING_LIMIT)),
            heat_missing=heat_missing, master_on=self.master_on, hvac_off=z.hvac_off,
            learning_paused=paused, window_wait_until=self._window_wait_until(z, now_ts), sofi=self.sofi_active(z),
            hand_until=self.hand_until(z, now_ts),
            sensor_mode=z.controller.sensor_mode, sensor_last_ts=z.controller.last_ts, note=note,
        )
        z.explanation = explain(sit)
        p = z.controller.params
        info: dict[str, Any] = {
            "grund": sit.reason, "soll": tg.setpoint, "ist": None if z.temp is None else round(z.temp, 2),
            "ventil": valve_now, "ventil_geplant": want,
            "naechster_wechsel": f"{_hhmm(nxt[0])} → {nxt[1]:.1f} °C".replace(".", ",") if nxt else None,
            "vorheizstart": _when(preheat_ts, now_ts) if preheat_ts else None,
            "sonne_3h_k": round(sun3, 2),
            "zusatzwaerme_k_h": round(z.controller.d, 3), "grundwaerme_k_h": round(p.g0, 3),
            "modellfehler_k_h": round(rmse, 3), "lernfortschritt": round(100 * z.learner.progress()),
            "lernt": not summer and paused is None and not z.window_open,
            "lernpause": "Sommer" if summer else ("Fenster offen" if z.window_open else paused),
            "heizperiode": not summer,
            "vorlauf": None if self.supply_shown is None else round(self.supply_shown, 1),
            "vorlauf_quelle": "gemessen" if self.supply.measured(now_ts) is not None else "Heizkurve",
        }
        if plan is not None:
            info["plan"] = [
                {"zeit": _hhmm(now_ts + float(h) * 3600), "soll": self.target_at(z, now_ts + float(h) * 3600).setpoint,
                 "prognose": round(float(tp), 2), "ventil": int(round(100 * valve_from_effective(float(u), p.valve_exp)))}
                for h, tp, u in zip(plan.times_h, plan.t_pred, plan.u)
            ]
        if self.vac_active(now_ts) and self.vac_setback is not None:
            info["urlaub"] = {
                "absenken": self.vac_setback,
                "ersparnis_prozent": round(100 * (self.vac_frac or 0.0)),
                "ersparnis_kwh": round(self.vac_kwh or 0.0, 1),
                "vorheizen_spaetestens": _when(z.vac_preheat_ts, now_ts) if self.vac_setback and z.vac_preheat_ts else None,
                "heizt_vor": z.vac_preheating,
            }
        z.info = info

        probs: list[str] = []
        if z.temp is None:
            probs.append("Kein Raumwert – Sensor meldet sich nicht")
        elif z.primary_missing and z.cfg.get(CONF_TEMP2):
            probs.append("Hauptsensor meldet sich nicht – nutze den Zweitsensor")
        for w in z.cfg.get(CONF_WINDOWS, []):
            st = self.hass.states.get(w)
            since = self._start_ts if st is None else st.last_changed.timestamp()
            if (st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)) and now_ts - since >= CONTACT_NOTICE_S:
                probs.append(f"Kontakt {w if st is None else st.name} nicht erreichbar – zählt als geschlossen")
        for t in z.trvs:
            if not t.available():
                probs.append(f"Thermostat {t.climate_id} nicht erreichbar")
            elif z.controlling and t.is_off():
                probs.append(f"Thermostat {t.climate_id} steht auf Aus – wird wieder eingeschaltet")
            elif z.controlling and t.write_mismatch(now_ts):
                probs.append(f"Thermostat {t.climate_id} übernimmt die Ventilstellung nicht")
            elif z.controlling and t.revived_ts is not None and now_ts - t.revived_ts < TRV_NOTICE_S:
                probs.append(f"Thermostat {t.climate_id} stand auf Aus und wurde wieder eingeschaltet")
            if z.controlling and t.error_ts is not None and now_ts - t.error_ts < TRV_NOTICE_S:
                probs.append(f"Thermostat {t.climate_id}: Befehl fehlgeschlagen")
        if d and d.reason == "rueckfall":
            probs.append("Sicherheitsbetrieb – Modell passt gerade nicht")
        if heat_missing:
            probs.append("Kessel liefert keine Wärme (Vorlauf kalt trotz offenem Ventil)")
        if self.doors_forgotten(now_ts):
            probs.append("Schalter „Türen offen“ seit über 12 h an – solange lernt die Heizung nicht")
        z.problems = probs
        # Flugschreiber für den Diagnose-Download: jede Entscheidung mit Grund und Eingängen (nur im Speicher)
        z.log.append({
            "zeit": dt_util.as_local(dt_util.utc_from_timestamp(now_ts)).strftime("%d.%m. %H:%M:%S"),
            **{k: v for k, v in info.items() if k != "plan"},
            "aussen": None if self.t_out is None else round(self.t_out, 1),
            "sonne_fassaden": [round(s, 3) for s in self.sun_now],
            "rohr": None if self.supply_pipe is None else round(self.supply_pipe, 1),
            "rohr_status": self.supply_note,
            "fenster_offen": z.window_open,
            "probleme": probs,
        })

    @staticmethod
    def _exercise_due(z: Zone, now_ts: float, local: datetime) -> bool:
        """Sonntags 11 Uhr, wenn das Ventil seit über einer Woche zu war."""
        return local.weekday() == 6 and local.hour == 11 and local.minute < 10 and now_ts - z.last_open_ts > 7 * 86400

    async def _actuate(self, z: Zone, dec: Decision, now_ts: float, controlling: bool, force: bool = False) -> None:
        if not controlling:
            if z.controlled:
                for t in z.trvs:
                    try:
                        await t.release(self.comfort_of(z))
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("%s: TRV %s freigeben fehlgeschlagen: %s", z.name, t.climate_id, err)
                z.controlled = False
                z.gate = ValveGate()
                z.last_ext_temp = None  # beim nächsten Übernehmen sofort die Raumtemperatur schicken
            z.valve_pct = 0
            return
        want = int(round(100 * dec.valve))
        first = not z.controlled
        force = force or first or dec.reason in ("fenster", "frostschutz")
        sent = z.gate.decide(now_ts, want, force=force)
        # bei Änderung, sonst spätestens alle 30 min (der Kopf soll den Fühler nicht für ausgefallen halten)
        send_ext = z.temp is not None and (
            z.last_ext_temp is None or abs(z.temp - z.last_ext_temp) >= 0.3 or now_ts - z.last_ext_ts >= EXT_TEMP_REFRESH_S
        )
        all_ok = True
        for t in z.trvs:
            try:
                # jedes Mal prüfen: Kopf kann inzwischen aus sein oder war beim Übernehmen nicht erreichbar
                await t.ensure_control(now_ts, first=first)
                if sent is not None:
                    await t.set_valve(sent)
                else:
                    await t.resync(now_ts)  # Befehl nicht angekommen → noch einmal senden
                if send_ext:
                    await t.set_room_temperature(z.temp)
            except Exception as err:  # noqa: BLE001 – ein TRV darf die anderen nicht blockieren
                t.error_ts = now_ts
                all_ok = False
                _LOGGER.warning("%s: TRV %s nicht erreichbar: %s", z.name, t.climate_id, err)
        if send_ext and all_ok:
            z.last_ext_temp, z.last_ext_ts = z.temp, now_ts
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
            c.u_prev = None
            comfort = c.make_plan(now_ts, x, lambda ts: Target(self.comfort_of(z), True), self.t_out_at(now_ts), self.sun_at(now_ts))
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
        # mit den Nachbarräumen: Das Bad (23,5 °C) verliert seine Wärme vor allem an die kühleren Räume nebenan –
        # ohne sie zeigte es ~0 W Bedarf, während das Ventil nachts auf 100 % stand
        others = [o.temp for o in self.zones.values() if o is not z and o.temp is not None]
        t_nbr = sum(others) / len(others) if others else None
        demand = steady_heat_demand(z.controller.params, tgt.setpoint, self.t_out, t_nbr)
        return 1000 * demand * z.controller.params.c_eff_kwh_per_k

    def estimated_supply(self) -> float | None:
        """Vorlauf jetzt (Anzeige): gemessen, wenn der Fühler gerade gültig ist, sonst aus der Heizkurve."""
        return self.supply_shown
