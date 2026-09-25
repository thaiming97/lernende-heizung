"""Thermisches 2-Knoten-Zonenmodell (Raumluft + Speichermasse) mit träger Heizkörperwirkung.

Einheiten: Temperaturen in °C, Zeit in Stunden, Koeffizienten in 1/h, Heizwirkung in K/h.
Kein Home-Assistant-Import – der Kern ist eigenständig test- und simulierbar.

    dT/dt  = k_am·(Tm − T) + k_n·(Tn − T) + k_o·(To − T) + Σ g_j·S_j + g0 + q + d   (S_j: Sonne auf Ost/Süd/West)
    dTm/dt = k_ma·(T − Tm) + k_mb·(t_b − Tm)
    dq_i/dt = (u_eff · φ(Tvl, T) · w_i(To) − q_i) / tau_rad,   q = Σ h_i · q_i

u_eff = v**valve_exp ist die wirksame Ventilöffnung (TRV-Kennlinie), φ die normierte
Heizkörperleistung (1 bei Nennbedingungen 75/65/20 °C, Exponent 1,3), w_i Dreiecksgewichte an
den Außentemperatur-Ankern −10/0/+10 °C. Die gelernten h_i enthalten damit auch Fehler der
angenommenen Heizkurve – daraus lässt sich die echte Heizkurve rückrechnen. g0 ist die dauerhafte
Grundwärme (Personen, Geräte), d nur der kurzfristige Rest, den der Regler laufend schätzt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import math

ANCHORS = (-10.0, 0.0, 10.0)
RAD_EXP = 1.3
NOMINAL_EXCESS = 50.0  # K (75/65/20 °C)
RETURN_DROP = 8.0  # K Spreizung Vorlauf→Rücklauf bei offenem Ventil (Annahme)


def anchor_weights(t_out: float) -> tuple[float, float, float]:
    """Dreiecks-Interpolationsgewichte der Außentemperatur auf die Anker (Summe 1)."""
    a0, a1, a2 = ANCHORS
    if t_out <= a0:
        return (1.0, 0.0, 0.0)
    if t_out >= a2:
        return (0.0, 0.0, 1.0)
    if t_out <= a1:
        f = (t_out - a0) / (a1 - a0)
        return (1.0 - f, f, 0.0)
    f = (t_out - a1) / (a2 - a1)
    return (0.0, 1.0 - f, f)


@dataclass
class HeatingCurve:
    """Vorlauftemperatur über Außentemperatur (linear, begrenzt), optional mit Versatz je
    Tagesstunde (z. B. Nachtabsenkung des Kessels, gelernt aus dem Vorlauffühler)."""

    tvl_at_m10: float = 55.0
    tvl_at_p15: float = 35.0
    tvl_min: float = 28.0
    tvl_max: float = 70.0
    hour_offset: tuple[float, ...] = ()  # 24 Werte in K (lokale Stunde), leer = keiner

    def supply(self, t_out: float, hour: int | None = None) -> float:
        slope = (self.tvl_at_p15 - self.tvl_at_m10) / 25.0
        tvl = self.tvl_at_m10 + slope * (t_out + 10.0)
        if hour is not None and len(self.hour_offset) == 24:
            tvl += self.hour_offset[hour % 24]
        return min(self.tvl_max, max(self.tvl_min, tvl))


def radiator_factor(t_supply: float, t_room: float) -> float:
    """Normierte Heizkörperleistung φ (1 = Nennleistung)."""
    excess = t_supply - RETURN_DROP / 2.0 - t_room
    if excess <= 0:
        return 0.0
    return (excess / NOMINAL_EXCESS) ** RAD_EXP


def curve_rescale(old: HeatingCurve, new: HeatingCurve, t_room: float = 21.0) -> tuple[float, float, float]:
    """Faktoren für die gelernte Heizwirkung h an den Außentemperatur-Ankern, wenn sich die
    angenommene Heizkurve ändert: h·φ soll gleich bleiben (h enthält sonst den alten Kurvenfehler)."""
    out = []
    for a in ANCHORS:
        p_old = radiator_factor(old.supply(a), t_room)
        p_new = radiator_factor(new.supply(a), t_room)
        f = p_old / p_new if p_new > 1e-3 else 1.0
        out.append(min(3.0, max(1 / 3, f)))
    return (out[0], out[1], out[2])


@dataclass
class ZoneParams:
    """Parameter einer Zone. Startwerte = Priors, die das Online-Lernen verfeinert."""

    k_am: float = 0.05
    k_ma: float = 0.02
    k_n: float = 0.01
    k_o: float = 0.003
    k_mb: float = 0.0
    t_b: float = 19.0
    g_sun: tuple[float, float, float] = (0.1, 0.2, 0.1)  # K/h je kW/m² Sonne auf Ost-/Süd-/Westfassade
    g0: float = 0.0  # K/h dauerhafte Grundwärme (Personen, Geräte)
    h: tuple[float, float, float] = (1.3, 1.3, 1.3)  # K/h bei Nennleistung, je Außentemperatur-Anker
    valve_exp: float = 0.6
    tau_rad: float = 0.35
    c_eff_kwh_per_k: float = 2.0  # wirksame Wärmekapazität (für Leistung/Energie in kW/kWh)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["h"] = list(self.h)
        d["g_sun"] = list(self.g_sun)
        return d

    @classmethod
    def from_dict(cls, raw: dict) -> ZoneParams:
        base = cls()
        kw = {}
        for k, v in raw.items():
            if not hasattr(base, k):
                continue
            if k in ("h", "g_sun"):
                vals = [float(x) for x in v] if isinstance(v, (list, tuple)) else []
                if len(vals) == 3 and all(math.isfinite(x) and x >= 0 for x in vals):
                    kw[k] = tuple(vals)
            else:
                fv = float(v)
                if math.isfinite(fv):
                    kw[k] = fv
        return replace(base, **kw)

    def heat_gain(self, t_out: float) -> float:
        """Heizwirkung bei Nennbedingungen (K/h) an dieser Außentemperatur."""
        w = anchor_weights(t_out)
        return sum(wi * hi for wi, hi in zip(w, self.h))


@dataclass
class ZoneState:
    """Dynamischer Zustand einer Zone (Masse und Heizkörper-Anteile sind nicht messbar)."""

    t: float = 21.0
    tm: float = 21.0
    q: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def copy(self) -> ZoneState:
        return ZoneState(self.t, self.tm, list(self.q))


@dataclass
class Inputs:
    """Randbedingungen für einen Zeitschritt."""

    t_out: float
    t_nbr: float | None = None
    sun: tuple[float, float, float] = (0.0, 0.0, 0.0)  # kW/m² auf Ost-/Süd-/Westfassade
    t_supply: float | None = None  # gemessener/geschätzter Vorlauf


def effective_valve(v: float, valve_exp: float) -> float:
    v = min(1.0, max(0.0, v))
    return v ** valve_exp if v > 0 else 0.0


def valve_from_effective(u: float, valve_exp: float) -> float:
    u = min(1.0, max(0.0, u))
    return u ** (1.0 / valve_exp) if u > 0 else 0.0


def derivatives(p: ZoneParams, s: ZoneState, x: Inputs, disturbance: float = 0.0) -> float:
    """dT/dt ohne Heizkörper-Zustandsänderung (Hilfsfunktion)."""
    tn = s.t if x.t_nbr is None else x.t_nbr
    q = sum(h * qi for h, qi in zip(p.h, s.q))
    return (
        p.k_am * (s.tm - s.t)
        + p.k_n * (tn - s.t)
        + p.k_o * (x.t_out - s.t)
        + sum(g * si for g, si in zip(p.g_sun, x.sun))
        + p.g0
        + q
        + disturbance
    )


def step(
    p: ZoneParams,
    s: ZoneState,
    x: Inputs,
    u_eff: float,
    dt: float,
    curve: HeatingCurve,
    disturbance: float = 0.0,
    t_measured: float | None = None,
) -> ZoneState:
    """Ein Zeitschritt (dt in h). Mit ``t_measured`` wird T nicht simuliert, sondern gesetzt
    (Datenassimilation: Masse und Heizkörper folgen der gemessenen Raumtemperatur)."""
    t_sup = x.t_supply if x.t_supply is not None else curve.supply(x.t_out)
    phi = radiator_factor(t_sup, s.t)
    w = anchor_weights(x.t_out)
    a = 1.0 - math.exp(-dt / max(p.tau_rad, 1e-3))
    q_new = [qi + (u_eff * phi * wi - qi) * a for qi, wi in zip(s.q, w)]
    dT = derivatives(p, s, x, disturbance)
    dTm = p.k_ma * (s.t - s.tm) + p.k_mb * (p.t_b - s.tm)
    t_new = s.t + dT * dt if t_measured is None else t_measured
    return ZoneState(t_new, s.tm + dTm * dt, q_new)


def heating_power_kw(p: ZoneParams, s: ZoneState) -> float:
    """Aktuelle Heizleistung (kW), geschätzt über die wirksame Wärmekapazität."""
    q = sum(h * qi for h, qi in zip(p.h, s.q))
    return max(0.0, q) * p.c_eff_kwh_per_k


def steady_heat_demand(p: ZoneParams, t_room: float, t_out: float, t_nbr: float | None = None) -> float:
    """Dauer-Wärmebedarf (K/h), wenn Raum und Masse im Gleichgewicht bei t_room stehen."""
    tn = t_room if t_nbr is None else t_nbr
    # Masse im Gleichgewicht: tm = (k_ma·T + k_mb·t_b)/(k_ma + k_mb)
    denom = p.k_ma + p.k_mb
    tm = t_room if denom <= 0 else (p.k_ma * t_room + p.k_mb * p.t_b) / denom
    loss = p.k_am * (tm - t_room) + p.k_n * (tn - t_room) + p.k_o * (t_out - t_room)
    return max(0.0, -loss - p.g0)
