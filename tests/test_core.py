"""Tests für den HA-unabhängigen Regelkern."""

from __future__ import annotations

from datetime import datetime
import copy
import math
import random
from zoneinfo import ZoneInfo

import pytest

from custom_components.lernende_heizung.core.actuator import ValveGate, trvzb_sequence
from custom_components.lernende_heizung.core.controller import (
    REASON_FALLBACK,
    REASON_FROST,
    REASON_NO_SENSOR,
    REASON_OFF,
    REASON_WINDOW,
    ControllerConfig,
    Target,
    ZoneController,
)
from custom_components.lernende_heizung.core.learning import ZoneLearner
from custom_components.lernende_heizung.core.model import (
    HeatingCurve,
    Inputs,
    ZoneParams,
    ZoneState,
    effective_valve,
    step,
    valve_from_effective,
)
from custom_components.lernende_heizung.core.schedule import ScheduleError, WeekSchedule
from custom_components.lernende_heizung.core.signals import OutdoorFusion, RoomSensorFilter, SunModel, SupplyLearner

TZ = ZoneInfo("Europe/Berlin")
NO_SUN = (0.0, 0.0, 0.0)


# ----------------------------------------------------------------------------- Zeitplan
def test_schedule_parse_and_lookup():
    s = WeekSchedule.parse("Mo-Fr 06:00-08:00, 16:30-22:00; Sa-So 07:30-22:30")
    mon = datetime(2026, 1, 5, tzinfo=TZ)  # Montag
    assert s.is_comfort(mon.replace(hour=6, minute=10))
    assert not s.is_comfort(mon.replace(hour=10))
    assert s.is_comfort(mon.replace(hour=17))
    sat = datetime(2026, 1, 10, tzinfo=TZ)
    assert not s.is_comfort(sat.replace(hour=7))
    assert s.is_comfort(sat.replace(hour=9))
    nxt = s.next_change(mon.replace(hour=10))
    assert (nxt.hour, nxt.minute) == (16, 30)


def test_schedule_overnight_and_always():
    s = WeekSchedule.parse("Fr 22:00-02:00")
    fri = datetime(2026, 1, 9, 23, tzinfo=TZ)
    assert s.is_comfort(fri)
    assert s.is_comfort(fri.replace(day=10, hour=1))
    assert not s.is_comfort(fri.replace(day=10, hour=3))
    assert WeekSchedule.parse("immer").is_comfort(fri)


@pytest.mark.parametrize("bad", ["", "Mo 25:00-26:00", "Xy 08:00-09:00", "Mo-Fr acht bis neun"])
def test_schedule_errors(bad):
    with pytest.raises(ScheduleError):
        WeekSchedule.parse(bad)


# ----------------------------------------------------------------------------- Modell
def test_model_heats_and_cools():
    p = ZoneParams()
    curve = HeatingCurve()
    s = ZoneState(20.0, 20.0, [0, 0, 0])
    x = Inputs(t_out=0.0, t_nbr=20.0)
    for _ in range(24):
        s = step(p, s, x, 1.0, 1 / 12, curve)
    assert s.t > 20.5
    s2 = ZoneState(22.0, 22.0, [0, 0, 0])
    for _ in range(24):
        s2 = step(p, s2, Inputs(t_out=-5.0, t_nbr=20.0), 0.0, 1 / 12, curve)
    assert s2.t < 22.0


def test_valve_characteristic_roundtrip():
    for v in (0.0, 0.1, 0.5, 1.0):
        assert math.isclose(valve_from_effective(effective_valve(v, 0.5), 0.5), v, abs_tol=1e-9)


# ----------------------------------------------------------------------------- Regler
def _run_ctrl(ctrl: ZoneController, t0: float, temp: float, target, hours: float, p: ZoneParams, x: Inputs):
    """Regler gegen dasselbe Modell laufen lassen; gibt Temperaturverlauf zurück."""
    curve = HeatingCurve()
    s = ZoneState(temp, temp - 0.2, [0, 0, 0])
    out = []
    u = 0.0
    for k in range(int(hours * 12)):
        ts = t0 + k * 300
        ctrl.observe(ts, s.t, x, u)
        dec = ctrl.decide(ts, s.t, x, target, lambda _t: x.t_out, lambda _t: NO_SUN)
        u = dec.u_eff
        s = step(p, s, x, u, 1 / 12, curve)
        out.append((ts, s.t, dec))
    return out


def test_controller_preheats_before_comfort():
    p = ZoneParams(k_am=0.05, k_ma=0.02, k_n=0.01, k_o=0.003, h=(1.5, 1.5, 1.5))
    x = Inputs(t_out=0.0, t_nbr=20.5)
    t0 = 1_767_600_000.0
    start = t0 + 6 * 3600  # Komfort beginnt in 6 h

    def target(ts):
        return Target(21.5, True) if ts >= start else Target(19.0, False)

    ctrl = ZoneController(p)
    run = _run_ctrl(ctrl, t0, 20.5, target, 8, p, x)
    # vorheizen erkannt, rechtzeitig warm, ohne Überschwingen
    assert any(d.reason == "vorheizen" for ts, _, d in run if ts < start)
    at_start = next(t for ts, t, _ in run if ts >= start)
    assert at_start >= 21.2, f"zu kalt bei Komfortbeginn: {at_start:.2f}"
    assert max(t for _, t, _ in run) < 22.0  # kein nennenswertes Überschwingen


def test_controller_safety_layers():
    ctrl = ZoneController(ZoneParams())
    x = Inputs(t_out=0.0)
    tgt = lambda _ts: Target(21.0, True)  # noqa: E731
    ctrl.observe(0.0, 20.0, x, 0.0)
    assert ctrl.decide(0.0, 20.0, x, tgt, lambda t: 0.0, lambda t: NO_SUN, window_open=True).reason == REASON_WINDOW
    assert ctrl.decide(0.0, 5.0, x, tgt, lambda t: 0.0, lambda t: NO_SUN).reason == REASON_FROST
    assert ctrl.decide(0.0, 5.0, x, tgt, lambda t: 0.0, lambda t: NO_SUN).valve == 1.0
    assert ctrl.decide(0.0, 20.0, x, tgt, lambda t: 0.0, lambda t: NO_SUN, enabled=False).reason == REASON_OFF
    d = ctrl.decide(0.0, None, x, tgt, lambda t: 0.0, lambda t: NO_SUN)
    assert d.reason == REASON_NO_SENSOR and 0 < d.valve < 1


def test_controller_export_restore():
    c = ZoneController(ZoneParams())
    c.observe(0.0, 20.0, Inputs(t_out=0.0), 0.0)
    c.observe(300.0, 20.1, Inputs(t_out=0.0), 0.0)
    c2 = ZoneController(ZoneParams())
    c2.restore(c.export())
    assert c2.state is not None and math.isclose(c2.state.t, c.state.t)
    c2.restore({"state": {"t": float("nan"), "tm": 1, "q": [0, 0, 0]}})  # kaputte Daten ignorieren


def test_disturbance_frozen_while_window_open():
    c = ZoneController(ZoneParams())
    x = Inputs(t_out=0.0, t_nbr=21.0)
    c.observe(0.0, 21.0, x, 0.0)
    for k in range(1, 12):  # Fenster offen: 1,2 K/h Auskühlen
        c.observe(k * 300.0, 21.0 - 0.1 * k, x, 0.0, freeze_d=True)
    assert c.d == 0.0
    for k in range(12, 24):
        c.observe(k * 300.0, 21.0 - 0.1 * k, x, 0.0)
    assert c.d < -0.1


def test_plan_disturbance_fades():
    p = ZoneParams(k_am=0.05, k_ma=0.02, k_n=0.0, k_o=0.003, h=(1.5, 1.5, 1.5))
    x = Inputs(t_out=5.0)
    tgt = lambda _ts: Target(15.0, False)  # noqa: E731 – nichts zu tun, Ventil bleibt zu
    rises = []
    for tau in (2.0, 1e6):
        c = ZoneController(p, cfg=ControllerConfig(d_tau_h=tau))
        c.observe(0.0, 21.0, x, 0.0)
        c.d = 0.5  # z. B. Kochen
        plan = c.make_plan(0.0, x, tgt, lambda _t: 5.0, lambda _t: NO_SUN)
        assert plan.u.max() < 0.01
        assert plan.t_pred[3] > 21.2  # kurzfristig wirkt die Störung voll
        rises.append(plan.t_pred[-1] - 21.0)
    # abklingend: höchstens ~1 K in 12 h; konstant fortgeschrieben wären es mehrere Kelvin
    assert rises[0] < 1.0 < 2.0 < rises[1]


def test_fallback_when_model_fails():
    c = ZoneController(ZoneParams())
    x = Inputs(t_out=0.0)
    tgt = lambda _ts: Target(21.0, True)  # noqa: E731
    c.observe(0.0, 20.0, x, 0.0)
    c.d = -0.6  # Störgröße am Anschlag: Modell erklärt die Messung nicht
    reasons = [c.decide(k * 300.0, 20.0, x, tgt, lambda _t: 0.0, lambda _t: NO_SUN).reason for k in range(30)]
    assert reasons[0] != REASON_FALLBACK and reasons[-1] == REASON_FALLBACK
    dec = c.decide(30 * 300.0, 20.0, x, tgt, lambda _t: 0.0, lambda _t: NO_SUN)
    assert dec.reason == REASON_FALLBACK and dec.valve > 0.5  # 1 K zu kalt → kräftig auf
    c.d = 0.0  # Modell passt wieder → vorausschauend
    assert c.decide(31 * 300.0, 20.0, x, tgt, lambda _t: 0.0, lambda _t: NO_SUN).reason != REASON_FALLBACK
    # Aufrufer meldet großen Modellfehler → sofort Rückfall
    assert c.decide(32 * 300.0, 20.0, x, tgt, lambda _t: 0.0, lambda _t: NO_SUN, use_fallback=True).reason == REASON_FALLBACK


# ----------------------------------------------------------------------------- Lernen
def test_learner_recovers_parameters():
    truth = ZoneParams(k_am=0.06, k_ma=0.02, k_n=0.012, k_o=0.003, g_sun=(0.1, 0.6, 0.0), h=(1.4, 1.4, 1.4), valve_exp=0.5, g0=0.1)
    prior = ZoneParams(k_am=0.04, k_ma=0.02, k_n=0.01, k_o=0.004, h=(2.2, 2.2, 2.2))
    L = ZoneLearner(prior)
    curve = HeatingCurve()
    rnd = random.Random(3)
    s = ZoneState(21.0, 20.8, [0, 0, 0])
    v = 0.0
    for k in range(12 * 24 * 21):  # 3 Wochen in 5-min-Schritten
        ts = k * 300.0
        hour = (k // 12) % 24
        if k % 18 == 0:
            v = rnd.choice([0, 0, 0.1, 0.3, 0.6, 1.0])
        sun = (0.0, 0.3 * max(0, math.sin((hour - 7) / 10 * math.pi)), 0.0) if 7 <= hour <= 17 else NO_SUN
        x = Inputs(t_out=rnd.uniform(-5, 8), t_nbr=21.0 + rnd.uniform(-0.5, 0.5), sun=sun)
        L.add(ts, s.t + rnd.gauss(0, 0.02), x, v)
        s = step(truth, s, x, effective_valve(v, truth.valve_exp), 1 / 12, curve)
    p = L.params()
    assert L.progress() > 0.9
    assert abs(p.heat_gain(0.0) - 1.4) / 1.4 < 0.35, p.h
    assert p.valve_exp in (0.35, 0.5, 0.7)
    assert p.g_sun[1] > 0.2
    assert 0.04 < p.g0 < 0.2, p.g0  # Grundwärme erkannt


def test_learner_export_restore_and_migration():
    prior = ZoneParams()
    L = ZoneLearner(prior)
    x = Inputs(t_out=0.0, t_nbr=21.0)
    for k in range(40):
        L.add(k * 300.0, 21.0 - 0.01 * k, x, 0.3)
    raw = copy.deepcopy(L.export())
    L2 = ZoneLearner(prior)
    L2.restore(raw)
    assert L2.samples == L.samples > 0 and L2.last_ts == L.last_ts
    # Speichermasse überlebt den Neustart
    assert all(c2.state is not None and math.isclose(c2.state.tm, c.state.tm) for c, c2 in zip(L.cands, L2.cands))
    # alter Stand ohne Grundwärme (9 Parameter) wird übernommen, g0 startet beim Prior
    old = copy.deepcopy(raw)
    for rc in old["cands"]:
        rc["theta"] = rc["theta"][:9]
        rc["P"] = [row[:9] for row in rc["P"][:9]]
        del rc["state"]
    L3 = ZoneLearner(prior)
    L3.restore(old)
    assert L3.samples == L.samples and L3.params().g0 == prior.g0
    assert math.isclose(L3.params().k_am, L.params().k_am)
    # kaputte Daten ändern nichts
    bad = copy.deepcopy(raw)
    bad["cands"][3]["theta"][0] = float("nan")
    L4 = ZoneLearner(prior)
    L4.restore(bad)
    assert L4.samples == 0 and L4.cands[0].state is None


# ----------------------------------------------------------------------------- Ventil
def test_valve_gate():
    g = ValveGate()
    assert g.decide(0, 40) == 40
    assert g.decide(60, 44) is None  # zu kleine Änderung, zu früh
    assert g.decide(60, 0) == 0  # zu: sofort
    assert g.decide(120, 2) is None  # unter Mindestöffnung → bleibt zu
    assert g.decide(2000, 30) == 30
    assert g.decide(2000 + 3700, 33) == 33  # kleine Restabweichung nach Beruhigung


def test_trvzb_bump_on_close():
    assert trvzb_sequence(None, 40) == [40]
    assert trvzb_sequence(20, 40) == [40]
    assert trvzb_sequence(50, 20) == [60, 20]
    assert trvzb_sequence(95, 10) == [100, 10]


# ----------------------------------------------------------------------------- Signale
def test_outdoor_fusion_learns_bias():
    f = OutdoorFusion()
    for _ in range(40):
        f.update(3, 2.0, 4.5)  # lokaler Fühler +2,5 K zu warm
    assert abs(f.bias[3] - 2.5) < 0.1
    assert abs(f.update(3, None, 4.5) - 2.0) < 0.1


def test_room_filter_replaces_sun_spike():
    flt = RoomSensorFilter()
    ts = 0.0
    for _ in range(40):
        ts += 300
        assert abs(flt.update(ts, 22.0, 21.5) - 22.0) < 1e-9
    ts += 300
    val = flt.update(ts, 28.0, 21.6)
    assert flt.disturbed and abs(val - 22.1) < 0.2


def test_supply_learner_curve():
    sl = SupplyLearner()
    ts = 0.0
    rnd = random.Random(1)
    for _ in range(300):
        tout = rnd.uniform(-8, 12)
        pipe = 50.0 - 0.9 * tout - 2.0  # Rohr 2 K unter Vorlauf
        sl.update(ts, pipe, tout, valve=0.0)
        sl.update(ts + 60, pipe, tout, valve=0.8)
        sl.update(ts + 1500, pipe, tout, valve=0.8)
        ts += 3600
    assert abs(sl.supply(0.0) - 50.0) < 1.0
    assert abs(sl.b + 0.9) < 0.1


def test_sun_facades_orientation():
    sm = SunModel(50.3, 10.2)
    noon = datetime(2026, 1, 15, 12, 15, tzinfo=TZ).timestamp()
    e, s, w = sm.facades(noon, 1.0)
    assert s > e and s > w and s > 0.3
    night = datetime(2026, 1, 15, 23, tzinfo=TZ).timestamp()
    assert sm.facades(night, 1.0) == (0.0, 0.0, 0.0)


# ----------------------------------------------------------------------------- Version
def test_version_consistent_and_documented():
    """manifest.json, const.VERSION und CHANGELOG.md müssen zusammenpassen (daraus wird das Release)."""
    import json
    from pathlib import Path

    from custom_components.lernende_heizung.const import VERSION

    root = Path(__file__).parents[1]
    manifest = json.loads((root / "custom_components" / "lernende_heizung" / "manifest.json").read_text(encoding="utf8"))
    assert manifest["version"] == VERSION
    assert f"\n## {VERSION} " in (root / "CHANGELOG.md").read_text(encoding="utf8")
