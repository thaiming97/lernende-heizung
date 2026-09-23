"""Vorausschauender Zonenregler (MPC) mit Zustands- und Störgrößenschätzung.

Ablauf je Regeltakt (typisch 5 min):
1. Messwert glätten, Masse- und Heizkörperzustand mit der gemessenen Temperatur fortschreiben,
   Störgröße (Personen, Kochen, Modellfehler) aus der Vorhersageabweichung schätzen.
2. Alle 15 min: Ventilverlauf für die nächsten 12 h optimieren. Der Horizont reicht bis zum nächsten
   Komfortbeginn → rechtzeitiges Vorheizen ergibt sich von selbst; ebenso das frühe Abschalten vor
   einer Absenkung oder vor erwarteter Sonne.
3. Sicherheitsschicht: Fenster offen → zu; Frostschutz; Rückfall auf einfachen PI-Regler, wenn das
   Modell unzuverlässig ist oder Messwerte fehlen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import math

import numpy as np

from .model import (
    HeatingCurve,
    Inputs,
    ZoneParams,
    ZoneState,
    anchor_weights,
    effective_valve,
    radiator_factor,
    step,
    valve_from_effective,
)

# Gründe (für Statussensor / Übersetzung)
REASON_COMFORT = "komfort"
REASON_SETBACK = "absenkung"
REASON_PREHEAT = "vorheizen"
REASON_WINDOW = "fenster"
REASON_FROST = "frostschutz"
REASON_OFF = "aus"
REASON_FALLBACK = "rueckfall"
REASON_NO_SENSOR = "kein_sensor"


@dataclass
class Target:
    """Sollwert zu einem Zeitpunkt: untere Komfortgrenze und ob Komfortzeit ist."""

    setpoint: float
    comfort: bool


@dataclass
class ControllerConfig:
    step_h: float = 0.25
    horizon_h: float = 12.0
    # Stellgrößen-Blöcke: 16×15 min, dann 30-min-Blöcke
    fine_steps: int = 16
    w_low: float = 30.0  # Strafe je K² Unterschreitung und Schritt
    w_high: float = 6.0  # Strafe je K² Überschwingen in Komfortzeit
    w_energy: float = 0.05  # je K/h Heizwirkung und Schritt
    w_smooth: float = 1.0  # Ventilruhe (schont Batterie/Motor)
    w_warm: float = 0.0  # je K über Soll außerhalb der Komfortzeit; >0 heizt später/kräftiger (spart ~3 %, mehr Überschwingen)
    band_low: float = 0.1  # K unter Soll noch ok
    band_high: float = 0.3  # K über Soll noch ok (Komfortzeit)
    obs_gain: float = 0.6  # 1/h: Anpassgeschwindigkeit der Störgröße
    obs_limit: float = 0.6  # K/h
    meas_alpha: float = 0.35  # Glättung Messwert je 5-min-Takt
    frost_c: float = 7.0
    iters: int = 250


@dataclass
class Plan:
    u: np.ndarray
    t_pred: np.ndarray
    times_h: np.ndarray
    preheat_start_h: float | None
    reach_target_h: float | None


@dataclass
class Decision:
    u_eff: float
    valve: float
    reason: str
    plan: Plan | None = None
    disturbance: float = 0.0


@dataclass
class ZoneController:
    """Regler einer Zone. Zustand ist serialisierbar (für Neustarts)."""

    params: ZoneParams
    curve: HeatingCurve = field(default_factory=HeatingCurve)
    cfg: ControllerConfig = field(default_factory=ControllerConfig)
    state: ZoneState | None = None
    t_filt: float | None = None
    d: float = 0.0
    u_eff: float = 0.0
    last_plan_ts: float | None = None
    last_pred: float | None = None
    last_ts: float | None = None
    fallback_i: float = 0.0
    z_prev: np.ndarray | None = None
    plan: Plan | None = None

    # ------------------------------------------------------------------ Zustand
    def observe(self, ts: float, t_meas: float, x: Inputs, u_applied: float) -> None:
        """Messwert einarbeiten. ts in Sekunden, u_applied = wirksame Öffnung seit dem letzten Takt."""
        if self.state is None or self.last_ts is None or ts - self.last_ts > 6 * 3600:
            self.state = ZoneState(t_meas, t_meas - 0.2, [0.0, 0.0, 0.0])
            self.t_filt = t_meas
            self.last_ts = ts
            self.last_pred = None
            return
        dt = (ts - self.last_ts) / 3600.0
        if dt <= 0:
            return
        a = 1.0 - (1.0 - self.cfg.meas_alpha) ** (dt / (5 / 60))
        self.t_filt += a * (t_meas - self.t_filt)
        if self.last_pred is not None:
            innov = self.t_filt - self.last_pred
            k = 1.0 - math.exp(-self.cfg.obs_gain * dt)
            self.d += k * innov / max(dt, 1e-3)
            self.d = max(-self.cfg.obs_limit, min(self.cfg.obs_limit, self.d))
        # Masse/Heizkörper mit gemessener Temperatur fortschreiben
        self.state = step(self.params, self.state, x, u_applied, dt, self.curve, self.d, t_measured=self.t_filt)
        # Vorhersage für den nächsten Takt (gleiche Taktlänge angenommen)
        nxt = step(self.params, self.state, x, u_applied, dt, self.curve, self.d)
        self.last_pred = nxt.t
        self.last_ts = ts

    # ------------------------------------------------------------------ Planung
    def _blocks(self, n: int) -> np.ndarray:
        """Abbildung Stellgrößen-Blöcke → Zeitschritte (n × m)."""
        idx = []
        b = 0
        for k in range(n):
            if k < self.cfg.fine_steps:
                b = k
            else:
                b = self.cfg.fine_steps + (k - self.cfg.fine_steps) // 2
            idx.append(b)
        m = max(idx) + 1
        M = np.zeros((n, m))
        for k, j in enumerate(idx):
            M[k, j] = 1.0
        return M

    def make_plan(
        self,
        ts: float,
        x_now: Inputs,
        target_at: Callable[[float], Target],
        t_out_at: Callable[[float], float],
        sun_at: Callable[[float], float],
    ) -> Plan:
        cfg, p, s = self.cfg, self.params, self.state
        dt = cfg.step_h
        n = int(round(cfg.horizon_h / dt))
        times = ts + np.arange(1, n + 1) * dt * 3600.0
        t_out = np.array([t_out_at(ts + k * dt * 3600.0) for k in range(n)])
        sun = np.array([sun_at(ts + k * dt * 3600.0) for k in range(n)]) @ np.asarray(p.g_sun)
        tn = s.t if x_now.t_nbr is None else x_now.t_nbr
        # Heizwirkung je Schritt bei u=1 (φ bei aktueller Raumtemperatur eingefroren)
        b = np.empty(n)
        for k in range(n):
            tsup = x_now.t_supply if x_now.t_supply is not None else self.curve.supply(t_out[k])
            phi = radiator_factor(tsup, s.t)
            w = anchor_weights(t_out[k])
            b[k] = phi * sum(wi * hi for wi, hi in zip(w, p.h))
        a_rad = 1.0 - math.exp(-dt / max(p.tau_rad, 1e-3))
        q0 = sum(h * qi for h, qi in zip(p.h, s.q))

        # Freie Antwort (u = 0)
        free = np.empty(n)
        T, Tm, q = s.t, s.tm, q0
        for k in range(n):
            dT = p.k_am * (Tm - T) + p.k_n * (tn - T) + p.k_o * (t_out[k] - T) + sun[k] + q + self.d
            dTm = p.k_ma * (T - Tm) + p.k_mb * (p.t_b - Tm)
            q = q + (0.0 - q) * a_rad
            T, Tm = T + dT * dt, Tm + dTm * dt
            free[k] = T
        # Impulsantwort auf einen Schritt „u·b = 1"
        g = np.empty(n)
        T, Tm, q = 0.0, 0.0, 0.0
        for k in range(n):
            dT = p.k_am * (Tm - T) - (p.k_n + p.k_o) * T + q
            dTm = p.k_ma * (T - Tm) - p.k_mb * Tm
            q = q + ((1.0 if k == 0 else 0.0) - q) * a_rad
            T, Tm = T + dT * dt, Tm + dTm * dt
            g[k] = T
        # T[k] (Ende Schritt k) hängt von u_j (j ≤ k) ab; g[0] = 0 bildet die Heizkörper-Verzögerung ab
        G = np.zeros((n, n))
        for k in range(n):
            G[k, : k + 1] = g[k::-1] * b[: k + 1]
        M = self._blocks(n)
        Ge = G @ M

        targets = [target_at(float(t)) for t in times]
        low = np.array([tg.setpoint - cfg.band_low for tg in targets])
        high = np.array([tg.setpoint + cfg.band_high if tg.comfort else 1e3 for tg in targets])
        eco = np.array([0.0 if tg.comfort else 1.0 for tg in targets])
        warm_grad = cfg.w_warm * (Ge.T @ eco)  # konstanter Gradient des linearen „wärmer als nötig"-Terms (vereinfacht)
        bm = M.T @ b  # Energie je Block

        m = M.shape[1]
        z = np.clip(self.z_prev if self.z_prev is not None and len(self.z_prev) == m else np.full(m, self.u_eff), 0, 1)
        # Lipschitz-Schätzung
        L = 2 * (cfg.w_low + cfg.w_high) * float(np.sum(Ge * Ge)) + 8 * cfg.w_smooth + 1e-6
        eta = 1.0 / L
        y, z_old, tk = z.copy(), z.copy(), 1.0
        D = np.eye(m) - np.eye(m, k=-1)
        # Ventilruhe nur für die nächsten Schritte wichtig (Batterie); später darf der Plan kräftig heizen
        ws = np.full(m, cfg.w_smooth)  # gleichmäßig: sanfte Heizrampen, weniger Überschwingen (Simulation)
        for _ in range(cfg.iters):
            T_pred = free + Ge @ y
            r = -2 * cfg.w_low * np.maximum(0.0, low - T_pred) + 2 * cfg.w_high * np.maximum(0.0, T_pred - high)
            grad = Ge.T @ r + cfg.w_energy * bm + warm_grad
            du = D @ y
            du[0] = y[0] - self.u_eff
            grad += 2 * (D.T @ (ws * du))
            z_new = np.clip(y - eta * grad, 0.0, 1.0)
            tk1 = (1 + math.sqrt(1 + 4 * tk * tk)) / 2
            y = z_new + ((tk - 1) / tk1) * (z_new - z_old)
            z_old, tk = z_new, tk1
        z = z_old
        u_steps = M @ z
        T_pred = free + G @ u_steps
        self.z_prev = np.concatenate([z[1:], z[-1:]]) if m > 1 else z

        # Diagnose: Vorheizstart = erster Heizschritt vor einem Komfortbeginn in Absenkzeit
        preheat = None
        now_t = target_at(ts)
        if not now_t.comfort and any(tg.comfort for tg in targets):
            for k in range(n):
                if u_steps[k] > 0.05:
                    preheat = k * dt
                    break
                if targets[k].comfort:
                    break
        reach = None
        for k in range(n):
            if T_pred[k] >= targets[k].setpoint - cfg.band_low:
                reach = (k + 1) * dt
                break
        return Plan(u_steps, T_pred, (times - ts) / 3600.0, preheat, reach)

    # ------------------------------------------------------------------ Entscheidung
    def decide(
        self,
        ts: float,
        t_meas: float | None,
        x_now: Inputs,
        target_at: Callable[[float], Target],
        t_out_at: Callable[[float], float],
        sun_at: Callable[[float], float],
        *,
        window_open: bool = False,
        enabled: bool = True,
        use_fallback: bool = False,
        replan_s: float = 900.0,
    ) -> Decision:
        cfg = self.cfg
        if not enabled:
            self.u_eff = 0.0
            return Decision(0.0, 0.0, REASON_OFF)
        if t_meas is None or not math.isfinite(t_meas):
            # Kein Raumsensor: sicherer Mittelwert, bei Kälte mehr
            u = 0.35 if x_now.t_out > 0 else 0.5
            self.u_eff = u
            return Decision(u, valve_from_effective(u, self.params.valve_exp), REASON_NO_SENSOR)
        if t_meas < cfg.frost_c:
            self.u_eff = 1.0
            return Decision(1.0, 1.0, REASON_FROST)
        if window_open:
            self.u_eff = 0.0
            self.z_prev = None
            return Decision(0.0, 0.0, REASON_WINDOW, disturbance=self.d)

        tg = target_at(ts)
        if use_fallback:
            e = tg.setpoint - self.t_filt
            dt = 5 / 60
            self.fallback_i = max(-0.5, min(1.0, self.fallback_i + 0.3 * e * dt))
            u = max(0.0, min(1.0, 0.6 * e + self.fallback_i))
            self.u_eff = u
            return Decision(u, valve_from_effective(u, self.params.valve_exp), REASON_FALLBACK, disturbance=self.d)

        if self.last_plan_ts is None or ts - self.last_plan_ts >= replan_s - 1 or self.plan is None:
            self.plan = self.make_plan(ts, x_now, target_at, t_out_at, sun_at)
            self.last_plan_ts = ts
            self.u_eff = float(self.plan.u[0])
        u = self.u_eff
        if tg.comfort:
            reason = REASON_COMFORT
        elif u > 0.05 and self.plan and self.plan.preheat_start_h is not None:
            reason = REASON_PREHEAT
        else:
            reason = REASON_SETBACK
        return Decision(u, valve_from_effective(u, self.params.valve_exp), reason, self.plan, self.d)

    # ------------------------------------------------------------------ Persistenz
    def export(self) -> dict:
        return {
            "state": None if self.state is None else {"t": self.state.t, "tm": self.state.tm, "q": list(self.state.q)},
            "t_filt": self.t_filt,
            "d": self.d,
            "u_eff": self.u_eff,
            "last_ts": self.last_ts,
            "fallback_i": self.fallback_i,
        }

    def restore(self, raw: dict) -> None:
        try:
            st = raw.get("state")
            vals = [st["t"], st["tm"], *st["q"]] if st else []
            if st and all(math.isfinite(float(v)) for v in vals) and len(st["q"]) == 3:
                self.state = ZoneState(float(st["t"]), float(st["tm"]), [float(v) for v in st["q"]])
            for k in ("t_filt", "d", "u_eff", "last_ts", "fallback_i"):
                v = raw.get(k)
                if v is not None and math.isfinite(float(v)):
                    setattr(self, k, float(v))
        except (TypeError, ValueError, KeyError):
            self.state = None


def valve_percent(u_eff: float, params: ZoneParams) -> int:
    return int(round(100 * valve_from_effective(u_eff, params.valve_exp)))


__all__ = [
    "ControllerConfig",
    "Decision",
    "Plan",
    "Target",
    "ZoneController",
    "effective_valve",
    "valve_percent",
]
