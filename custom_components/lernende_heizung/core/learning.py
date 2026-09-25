"""Online-Lernen der Zonenparameter (rekursive kleinste Quadrate, Modellbank).

Linear lernbar sind k_am, k_n, k_o, g_sun, die Heizwirkung h (3 Außentemperatur-Anker) und die
Grundwärme g0.
Nicht linear sind Masse-Zeitkonstante (k_ma) und Ventilkennlinie (valve_exp) – dafür laufen
mehrere Kandidaten parallel, gewählt wird der mit dem kleinsten Vorhersagefehler.

Stichprobe alle 15 min: y = ΔT/Δt, Regressoren = Mittelwerte über das Intervall.
Ausgeschlossen: offenes Fenster (+30 min Nachlauf), Sensorsprünge, fehlende Werte.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math

from .model import (
    HeatingCurve,
    Inputs,
    ZoneParams,
    ZoneState,
    anchor_weights,
    curve_rescale,
    effective_valve,
    radiator_factor,
)

LIN = ("k_am", "k_n", "k_o", "g_e", "g_s", "g_w", "h0", "h1", "h2", "g0")
SAMPLE_H = 0.25


def _theta(p: ZoneParams) -> list[float]:
    return [p.k_am, p.k_n, p.k_o, *p.g_sun, *p.h, p.g0]


def _with_theta(p: ZoneParams, th: list[float]) -> ZoneParams:
    return replace(p, k_am=th[0], k_n=th[1], k_o=th[2], g_sun=(th[3], th[4], th[5]), h=(th[6], th[7], th[8]), g0=th[9])


@dataclass
class Rls:
    """RLS mit Vergessen, begrenzter Kovarianz und leichtem Zug zum Startwert (gegen Drift bei wenig Anregung)."""

    theta: list[float]
    P: list[list[float]]
    lam: float = 0.9995
    upper: list[float] = field(default_factory=list)
    prior: list[float] = field(default_factory=list)
    p0: list[float] = field(default_factory=list)
    leak: float = 0.0003

    @classmethod
    def from_prior(cls, th0: list[float], rel: float = 0.6, lam: float = 0.9995) -> Rls:
        n = len(th0)
        # Prior-Unsicherheit: relativ zum Startwert, mit Mindestbreite
        mins = [0.03, 0.01, 0.003, 0.2, 0.2, 0.2, 0.4, 0.4, 0.4, 0.1]
        P = [[0.0] * n for _ in range(n)]
        for i in range(n):
            s = max(abs(th0[i]) * rel, mins[i])
            P[i][i] = s * s
        upper = [max(1.0, 5 * th0[0]), 0.3, 0.05, 3.0, 3.0, 3.0, 6.0, 6.0, 6.0, 0.5]
        return cls(list(th0), P, lam, upper, list(th0), [P[i][i] for i in range(n)])

    def update(self, x: list[float], y: float, r: float) -> float:
        """Ein RLS-Schritt mit Messrauschvarianz r. Gibt den a-priori-Fehler zurück."""
        n = len(self.theta)
        e = y - sum(a * b for a, b in zip(x, self.theta))
        Px = [sum(self.P[i][j] * x[j] for j in range(n)) for i in range(n)]
        s = r + sum(x[i] * Px[i] for i in range(n))
        if s <= 0:
            return e
        k = [v / s for v in Px]
        th = [self.theta[i] + k[i] * e for i in range(n)]
        if self.prior:
            th = [t + self.leak * (p0 - t) for t, p0 in zip(th, self.prior)]
        self.theta = [min(self.upper[i], max(0.0, th[i])) for i in range(n)]
        lam = self.lam
        self.P = [[(self.P[i][j] - k[i] * Px[j]) / lam for j in range(n)] for i in range(n)]
        # Kovarianz auf die Startunsicherheit begrenzen (kein Wind-up bei fehlender Anregung)
        for i in range(n):
            cap = self.p0[i] if self.p0 else 4.0
            if self.P[i][i] > cap:
                f = math.sqrt(cap / self.P[i][i])
                for j in range(n):
                    self.P[i][j] *= f
                    self.P[j][i] *= f
        return e


@dataclass
class Candidate:
    k_ma: float
    valve_exp: float
    rls: Rls
    state: ZoneState | None = None
    score: float = 0.0
    n: int = 0


@dataclass
class _Acc:
    t0: float | None = None
    ts0: float | None = None
    n: int = 0
    sums: dict = field(default_factory=dict)
    valve_sum: float = 0.0
    bad: bool = False


class ZoneLearner:
    """Sammelt Messungen, lernt Parameter, liefert das aktuell beste Modell."""

    KMA_F = (0.5, 1.0, 2.0)
    VEXP = (0.35, 0.5, 0.7, 1.0)

    def __init__(self, prior: ZoneParams, curve: HeatingCurve | None = None) -> None:
        self.prior = prior
        self.curve = curve or HeatingCurve()
        self.cands: list[Candidate] = []
        for f in self.KMA_F:
            for ve in self.VEXP:
                self.cands.append(Candidate(prior.k_ma * f, ve, Rls.from_prior(_theta(prior))))
        self.best = 5  # k_ma×1, valve_exp 0.5
        self.acc = _Acc()
        self.samples = 0
        self.heat_samples = 0
        self.resid_var = 0.02
        self.blocked_until = 0.0
        self.last_ts: float | None = None
        # Heizkurve (Vorlauf bei −10/+15 °C), zu der die gelernte Heizwirkung h passt
        self.curve_ref = (HeatingCurve().tvl_at_m10, HeatingCurve().tvl_at_p15)

    # -------------------------------------------------------------- Messungen
    def block(self, until_ts: float) -> None:
        """Lernen pausieren (z. B. Fenster offen)."""
        self.blocked_until = max(self.blocked_until, until_ts)
        self.acc = _Acc()

    def add(self, ts: float, t_meas: float | None, x: Inputs, valve: float) -> None:
        """Messung alle paar Minuten. valve = tatsächlich gesendete Öffnung (0..1)."""
        if t_meas is None or not math.isfinite(t_meas) or ts < self.blocked_until:
            self.acc = _Acc()
            self._advance_states(ts, None, x, valve)
            return
        a = self.acc
        if a.t0 is None:
            self.acc = _Acc(t0=t_meas, ts0=ts)
            self._advance_states(ts, t_meas, x, valve)
            return
        a.n += 1
        for k, v in (("to", x.t_out), ("tn", x.t_nbr if x.t_nbr is not None else t_meas), ("t", t_meas),
                     ("se", x.sun[0]), ("ss", x.sun[1]), ("sw", x.sun[2])):
            a.sums[k] = a.sums.get(k, 0.0) + v
        a.valve_sum += valve
        self._advance_states(ts, t_meas, x, valve)
        dt = (ts - a.ts0) / 3600.0
        if dt >= SAMPLE_H - 1e-6:
            rate = (t_meas - a.t0) / dt
            if abs(rate) < 3.0 and a.n > 0:
                self._learn(rate, {k: v / a.n for k, v in a.sums.items()}, a.valve_sum / a.n, dt)
            self.acc = _Acc(t0=t_meas, ts0=ts)

    def _advance_states(self, ts: float, t_meas: float | None, x: Inputs, valve: float) -> None:
        if self.last_ts is None:
            self.last_ts = ts
            return
        dt = (ts - self.last_ts) / 3600.0
        self.last_ts = ts
        if dt <= 0 or dt > 2:
            for c in self.cands:
                c.state = None
            return
        tsup = x.t_supply if x.t_supply is not None else self.curve.supply(x.t_out)
        for c in self.cands:
            if c.state is None:
                t0 = t_meas if t_meas is not None else 21.0
                c.state = ZoneState(t0, t0 - 0.2, [0.0, 0.0, 0.0])
            s = c.state
            T = t_meas if t_meas is not None else s.t
            u = effective_valve(valve, c.valve_exp)
            phi = radiator_factor(tsup, T)
            w = anchor_weights(x.t_out)
            ar = 1.0 - math.exp(-dt / max(self.prior.tau_rad, 1e-3))
            s.q = [qi + (u * phi * wi - qi) * ar for qi, wi in zip(s.q, w)]
            s.tm += (c.k_ma * (T - s.tm) + self.prior.k_mb * (self.prior.t_b - s.tm)) * dt
            s.t = T

    def _learn(self, rate: float, m: dict, valve: float, dt: float) -> None:
        self.samples += 1
        if valve > 0.02:
            self.heat_samples += 1
        r = max(0.005, self.resid_var)
        for c in self.cands:
            s = c.state
            if s is None:
                continue
            x = [s.tm - m["t"], m["tn"] - m["t"], m["to"] - m["t"], m["se"], m["ss"], m["sw"], *s.q, 1.0]
            e = c.rls.update(x, rate, r)
            c.n += 1
            c.score = 0.997 * c.score + 0.003 * e * e if c.n > 1 else e * e
        best = min(range(len(self.cands)), key=lambda i: self.cands[i].score)
        if self.cands[best].score < 0.95 * self.cands[self.best].score:
            self.best = best
        self.resid_var = 0.99 * self.resid_var + 0.01 * self.cands[self.best].score

    def rescale_heat(self, f: tuple[float, float, float], estimates: bool = True) -> None:
        """Heizwirkung h (je Außentemperatur-Anker) umskalieren, z. B. wenn die Heizkurve gelernt
        wurde. Schätzwert, Startwert, Unsicherheit und Kovarianz werden konsistent mitgeführt.
        estimates=False: nur Startwerte/Grenzen (nach dem Laden sind die Schätzwerte schon skaliert)."""
        idx = (6, 7, 8)
        scale = [1.0] * len(LIN)
        for i, fi in zip(idx, f):
            scale[i] = fi
        self.prior = replace(self.prior, h=tuple(h * fi for h, fi in zip(self.prior.h, f)))
        for c in self.cands:
            r = c.rls
            if estimates:
                r.theta = [t * s for t, s in zip(r.theta, scale)]
                r.P = [[r.P[i][j] * scale[i] * scale[j] for j in range(len(scale))] for i in range(len(scale))]
            if r.prior:
                r.prior = [t * s for t, s in zip(r.prior, scale)]
            if r.p0:
                r.p0 = [v * s * s for v, s in zip(r.p0, scale)]
            r.upper = [u * max(1.0, s) for u, s in zip(r.upper, scale)]

    def adopt_curve(self, curve: HeatingCurve) -> None:
        """Neue Heizkurve übernehmen und die Heizwirkung so umrechnen, dass h·φ gleich bleibt."""
        ref = (curve.tvl_at_m10, curve.tvl_at_p15)
        if ref != self.curve_ref:
            old = HeatingCurve(tvl_at_m10=self.curve_ref[0], tvl_at_p15=self.curve_ref[1])
            f = curve_rescale(old, curve)
            # erst ab 2 % umrechnen: die gelernte Kurve wandert mit jeder Messung ein wenig
            if max(abs(v - 1.0) for v in f) >= 0.02:
                self.rescale_heat(f)
                self.curve_ref = ref
        self.curve = curve

    # -------------------------------------------------------------- Ergebnis
    def params(self) -> ZoneParams:
        c = self.cands[self.best]
        return _with_theta(replace(self.prior, k_ma=c.k_ma, valve_exp=c.valve_exp), c.rls.theta)

    def progress(self) -> float:
        """0..1: grobe Reife des Modells (Stichproben, davon mit Heizen)."""
        return min(1.0, 0.5 * min(1.0, self.samples / 1500) + 0.5 * min(1.0, self.heat_samples / 500))

    def rmse(self) -> float:
        """Wurzel des mittleren 15-min-Vorhersagefehlers (K/h)."""
        return math.sqrt(max(0.0, self.cands[self.best].score))

    # -------------------------------------------------------------- Persistenz
    def export(self) -> dict:
        return {
            "best": self.best, "samples": self.samples, "heat_samples": self.heat_samples,
            "resid_var": self.resid_var, "last_ts": self.last_ts, "curve_ref": list(self.curve_ref),
            "cands": [{"k_ma": c.k_ma, "valve_exp": c.valve_exp, "theta": c.rls.theta, "P": c.rls.P,
                       "score": c.score, "n": c.n,
                       "state": None if c.state is None else {"t": c.state.t, "tm": c.state.tm, "q": list(c.state.q)}}
                      for c in self.cands],
        }

    def restore(self, raw: dict) -> None:
        try:
            cands = raw["cands"]
            if len(cands) != len(self.cands):
                return
            n = len(LIN)
            loaded = []
            for c, rc in zip(self.cands, cands):
                th = [float(v) for v in rc["theta"]]
                P = [[float(v) for v in row] for row in rc["P"]]
                if len(th) == n - 1 and len(P) == n - 1:
                    # Stand vor der Grundwärme g0: Parameter übernehmen, g0 startet beim Prior
                    th.append(c.rls.theta[-1])
                    P = [row + [0.0] for row in P] + [[0.0] * (n - 1) + [c.rls.P[-1][-1]]]
                if len(th) != n or len(P) != n or any(len(row) != n for row in P):
                    return
                if not all(math.isfinite(v) for v in th) or not all(math.isfinite(v) for row in P for v in row):
                    return
                loaded.append((c, th, P, float(rc["score"]), int(rc["n"]), _state_from(rc.get("state"))))
            for c, th, P, score, cnt, st in loaded:
                c.rls.theta, c.rls.P, c.score, c.n, c.state = th, P, score, cnt, st
            self.best = int(raw["best"])
            self.samples = int(raw["samples"])
            self.heat_samples = int(raw["heat_samples"])
            self.resid_var = float(raw["resid_var"])
            lt = raw.get("last_ts")
            self.last_ts = float(lt) if lt is not None and math.isfinite(float(lt)) else None
            ref = raw.get("curve_ref")
            if isinstance(ref, list) and len(ref) == 2 and all(math.isfinite(float(v)) for v in ref):
                ref_t = (float(ref[0]), float(ref[1]))
                if ref_t != self.curve_ref:
                    # gespeicherte Schätzwerte passen schon zu ref; Startwerte/Grenzen nachziehen
                    old = HeatingCurve(tvl_at_m10=self.curve_ref[0], tvl_at_p15=self.curve_ref[1])
                    new = HeatingCurve(tvl_at_m10=ref_t[0], tvl_at_p15=ref_t[1])
                    self.rescale_heat(curve_rescale(old, new), estimates=False)
                    self.curve_ref = ref_t
        except (KeyError, TypeError, ValueError):
            return


def _state_from(raw) -> ZoneState | None:
    """Gespeicherten Kandidatenzustand (Speichermasse, Heizkörper) prüfen und übernehmen."""
    if not isinstance(raw, dict):
        return None
    try:
        vals = [float(raw["t"]), float(raw["tm"]), *[float(v) for v in raw["q"]]]
    except (KeyError, TypeError, ValueError):
        return None
    if len(vals) != 5 or not all(math.isfinite(v) for v in vals):
        return None
    return ZoneState(vals[0], vals[1], vals[2:])
