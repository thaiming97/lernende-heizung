"""Urlaub: lohnt sich das Absenken – und wann muss das Vorheizen spätestens beginnen?

Die Wohnung ist gut gedämmt und träge. Übers Wochenende kühlte sie nur 2–3 K ab, gespart war wenig, und das
Wiederaufheizen dauerte bei ~30 °C Vorlauf viele Stunden (live 23.–25.10.2026: um 18 Uhr noch 0,3–0,6 K zu kalt,
obwohl der Regler „just in time“ geplant hatte). Deshalb rechnet die Heizung beide Wege mit dem gelernten Modell:

- warm halten: Wärme, die das Halten der Komforttemperatur bis zur Rückkehr kostet,
- absenken: der Raum kühlt frei aus (höchstens bis zur Urlaubstemperatur), ab dem spätesten Start heizt er mit
  voller Leistung, zur Rückkehr ist es warm. Gespart ist der Wärmeverlust nach außen, den der kühlere Raum vermeidet.

Vorsichtig gerechnet: ohne Sonne und ohne Wärme aus Nachbarräumen (die kühlen ja mit), Heizkörper nur mit
HEAT_RESERVE ihrer gelernten Wirkung – über Stunden wirken sie schwächer, als das Modell aus 5-min-Schritten
lernt (Nachrechnung mit den Messwerten vom 17.–26.10.: 65–85 %).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import math

from .model import HeatingCurve, Inputs, ZoneParams, ZoneState, step, steady_heat_demand

HEAT_RESERVE = 0.65  # Anteil der gelernten Heizwirkung, mit dem das Vorheizen gerechnet wird
MIN_SAVING = 0.10  # absenken erst, wenn es so viel der Wärme fürs Warmhalten spart
STEP_H = 0.25
MAX_DAYS = 60  # weiter rechnet niemand voraus (Urlaub mit Rückkehr in einem halben Jahr …)


@dataclass
class VacationPlan:
    saving_kwh: float  # gespart gegenüber Warmhalten (inkl. Vorheizen)
    keep_kwh: float  # Wärme fürs Warmhalten bis zur Rückkehr
    preheat_ts: float  # spätester Start mit voller Leistung (= Rückkehr, wenn keins nötig)
    t_min: float  # tiefste Raumtemperatur bis dahin

    @property
    def saving_frac(self) -> float:
        return self.saving_kwh / self.keep_kwh if self.keep_kwh > 1e-6 else 0.0


def plan_vacation(
    p: ZoneParams,
    s: ZoneState,
    curve: HeatingCurve,
    hour_of: Callable[[float], int],
    now_ts: float,
    return_ts: float,
    comfort: float,
    away: float,
    t_out_at: Callable[[float], float],
    band: float = 0.1,
) -> VacationPlan:
    dt = STEP_H
    n = max(0, min(int(math.ceil((return_ts - now_ts) / 3600 / dt)), int(MAX_DAYS * 24 / dt)))
    times = [now_ts + k * dt * 3600 for k in range(n)]
    xs = []
    for ts in times:
        t_out = t_out_at(ts)
        xs.append(Inputs(t_out=t_out, t_supply=curve.supply(t_out, hour_of(ts))))
    keep = sum(steady_heat_demand(p, comfort, x.t_out) for x in xs) * dt * p.c_eff_kwh_per_k

    # Frei auskühlen (Ventil zu), unten hält die Urlaubstemperatur
    free = [ZoneState(s.t, s.tm, list(s.q))]
    for x in xs:
        nxt = step(p, free[-1], x, 0.0, dt, curve)
        if nxt.t < away:
            nxt = ZoneState(away, nxt.tm, nxt.q)
        free.append(nxt)

    heat = replace(p, h=tuple(h * HEAT_RESERVE for h in p.h))

    def heat_from(k0: int) -> list[float]:
        st, out = free[k0], []
        for x in xs[k0:]:
            st = step(heat, st, x, 1.0, dt, curve)
            if st.t > comfort:  # warm genug: hält die Komforttemperatur
                st = ZoneState(comfort, st.tm, st.q)
            elif st.t < away:  # Heizkörper braucht anfangs etwas, bis er warm ist
                st = ZoneState(away, st.tm, st.q)
            out.append(st.t)
        return out

    # Warm halten = durchheizen. Nachts schafft der Kessel (Absenkung) manchmal nicht ganz die Komforttemperatur
    # (Wohnen live 21,1–21,5 bei 100 %) – zur Rückkehr muss es so warm sein, wie es durchgeheizt wäre.
    keep_path = heat_from(0)
    goal = min(comfort, keep_path[-1] if keep_path else s.t) - band

    def warm_at_return(k0: int) -> bool:
        path = heat_from(k0)
        return (path[-1] if path else free[k0].t) >= goal

    if warm_at_return(n):
        k_start = n
    elif not warm_at_return(0):
        k_start = 0
    else:  # spätester Start: früher anfangen macht es zur Rückkehr nie kälter
        lo, hi = 0, n  # lo reicht, hi nicht
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if warm_at_return(mid):
                lo = mid
            else:
                hi = mid
        k_start = lo
    temps = [st.t for st in free[1 : k_start + 1]] + heat_from(k_start)
    saving = sum(max(0.0, tk - t) for tk, t in zip(keep_path, temps)) * dt * p.k_o * p.c_eff_kwh_per_k
    return VacationPlan(
        saving_kwh=saving,
        keep_kwh=keep,
        preheat_ts=now_ts + k_start * dt * 3600 if k_start < n else return_ts,
        t_min=min([s.t, *temps]),
    )


def worth_it(plans: list[VacationPlan]) -> tuple[bool, float, float]:
    """Gemeinsame Entscheidung für alle Zonen im Urlaub: (absenken?, Anteil gespart, kWh gespart)."""
    keep = sum(pl.keep_kwh for pl in plans)
    saving = sum(pl.saving_kwh for pl in plans)
    frac = saving / keep if keep > 1e-6 else 0.0
    return frac >= MIN_SAVING, frac, saving
