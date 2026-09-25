"""Klartext: was die Regelung gerade tut und warum (für den Sensor „Erklärung“).

Reine Textlogik ohne Home Assistant; alle Zahlen kommen fertig berechnet vom Coordinator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

MAX_LEN = 255  # Grenze für den Zustand einer HA-Entity


@dataclass
class Situation:
    reason: str
    temp: float | None
    setpoint: float
    valve_pct: int  # was gerade am Ventil steht (gestellt bzw. beobachtet)
    want_pct: int  # was der Regler stellen will/würde
    fmt_time: Callable[[float], str]
    next_change: tuple[float, float, bool] | None = None  # (Zeit, Sollwert, Komfort?)
    temp_at_change: float | None = None  # Prognose zum nächsten Wechsel
    temp_in_1h: float | None = None
    preheat_ts: float | None = None
    sun_3h_k: float = 0.0  # Erwärmung durch Sonne in den nächsten 3 h (Modell)
    disturbance: float = 0.0  # K/h kurzfristige Zusatzwärme (+) bzw. -kühlung (−)
    model_error: float = 0.0
    season: str = "auto"
    t_out_mean24: float | None = None
    heating_limit: float = 16.0
    heat_missing: bool = False
    master_on: bool = True
    hvac_off: bool = False
    learning_paused: str | None = None


def _n(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def explain(s: Situation) -> str:
    parts: list[str] = []
    t = s.temp
    sp = _n(s.setpoint)
    r = s.reason

    if r == "fenster":
        parts.append("Fenster offen – Ventil zu, Lernen pausiert.")
    elif r == "frostschutz":
        parts.append(f"Frostschutz: nur {_n(t or 0)} °C – Ventil ganz auf.")
    elif r == "sommer":
        if s.season == "sommer":
            parts.append("Sommerbetrieb (von Hand) – Heizung aus, Ventile zu, Lernen pausiert.")
        else:
            m = f"{_n(s.t_out_mean24)} °C" if s.t_out_mean24 is not None else "?"
            parts.append(f"Keine Heizperiode: außen im Mittel {m}, Heizgrenze {_n(s.heating_limit, 0)} °C – "
                         "Ventile zu, Lernen pausiert.")
    elif r == "kein_sensor":
        parts.append(f"Raumsensor meldet sich nicht – feste Öffnung {s.valve_pct} %.")
    elif r == "aus":
        if not s.master_on:
            parts.append("Regelung aus – die Thermostatköpfe regeln selbst.")
        else:
            parts.append("Zone aus – nur Frostschutz.")
    elif r == "rueckfall":
        parts.append(f"Sicherheitsbetrieb: Modell passt gerade nicht (Fehler {_n(s.model_error, 2)} K/h) – "
                     f"einfache Regelung auf {sp} °C, Ventil {s.valve_pct} %.")
    elif r == "beobachten":
        parts.append(f"Nur beobachten – Ventil steht auf {s.valve_pct} %, ich würde {s.want_pct} % stellen "
                     f"(Soll {sp} °C).")
    elif r == "vorheizen" and s.next_change:
        ts, nsp, _ = s.next_change
        parts.append(f"Heizt vor: {_n(nsp)} °C ab {s.fmt_time(ts)}, jetzt {_n(t or 0)} °C, Ventil {s.valve_pct} %.")
    elif r == "absenkung":
        until = f" bis {s.fmt_time(s.next_change[0])}" if s.next_change else ""
        parts.append(f"Absenkung auf {sp} °C{until}, jetzt {_n(t or 0)} °C.")
        if s.valve_pct == 0 and s.next_change and s.temp_at_change is not None:
            parts.append(f"Ventil zu, Raum kühlt langsam (Prognose {s.fmt_time(s.next_change[0])}: "
                         f"{_n(s.temp_at_change)} °C).")
        if s.preheat_ts:
            parts.append(f"Vorheizen ab ca. {s.fmt_time(s.preheat_ts)}.")
    else:  # komfort
        parts.append(f"Hält {sp} °C, jetzt {_n(t or 0)} °C – Ventil {s.valve_pct} %.")
        if s.valve_pct == 0 and t is not None:
            if s.sun_3h_k >= 0.3:
                parts.append(f"Ventil zu: Sonne bringt in 3 h ca. +{_n(s.sun_3h_k)} K.")
            elif t > s.setpoint + 0.1:
                parts.append(f"Ventil zu: {_n(t - s.setpoint)} K zu warm.")
            elif s.next_change and not s.next_change[2]:
                parts.append(f"Ventil zu: Absenkung ab {s.fmt_time(s.next_change[0])}, die Wärme reicht bis dahin.")
        if s.temp_in_1h is not None:
            parts.append(f"In 1 h {_n(s.temp_in_1h)} °C.")

    if r not in ("fenster", "sommer", "aus"):
        if s.disturbance >= 0.15:
            parts.append(f"Zusatzwärme erkannt (+{_n(s.disturbance, 2)} K/h, z. B. Kochen, Besuch).")
        elif s.disturbance <= -0.15:
            parts.append(f"Kühlt schneller als erwartet ({_n(s.disturbance, 2)} K/h).")
        if s.heat_missing:
            parts.append("Kessel liefert gerade keine Wärme (Vorlauf kalt).")
        if s.learning_paused and r != "fenster":
            parts.append(f"Lernen pausiert: {s.learning_paused}.")

    text = " ".join(parts)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"
