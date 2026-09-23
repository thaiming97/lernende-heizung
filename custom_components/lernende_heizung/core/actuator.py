"""Batterieschonende Ventilansteuerung für TRVs (reine Logik, ohne HA).

Jeder Schreibbefehl weckt den TRV und bewegt den Motor. Deshalb:
- Änderungen unter ``min_step`` Prozentpunkten werden nicht gesendet,
- zwischen zwei Befehlen liegen mindestens ``min_interval_s`` Sekunden,
- Ausnahmen: ganz zu (Fenster/Frost/Aus) und ganz auf werden sofort gesendet,
- kleine Restabweichungen werden nach ``settle_s`` trotzdem nachgeführt.
Sonoff TRVZB: beim Schließen erst kurz um ``bump`` weiter öffnen, dann auf Ziel
(Motor verliert sonst gelegentlich die Kalibrierung – Erfahrung aus Better Thermostat).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValveGate:
    min_step: int = 8
    min_interval_s: float = 1200.0
    settle_s: float = 3600.0
    small_step: int = 2
    min_open: int = 3
    last_sent: int | None = None
    last_ts: float | None = None

    def decide(self, ts: float, wanted: int, force: bool = False) -> int | None:
        """Gibt den zu sendenden Wert zurück oder None (nichts senden)."""
        wanted = max(0, min(100, int(round(wanted))))
        # Winzige Öffnungen sind am Ventil nicht reproduzierbar → zu
        if wanted < self.min_open:
            wanted = 0
        if self.last_sent is None or force:
            return self._send(ts, wanted)
        diff = abs(wanted - self.last_sent)
        if diff == 0:
            return None
        since = ts - (self.last_ts or 0)
        # Ganz zu / ganz auf immer sofort (Fenster, Frost, Vorheizen)
        if wanted in (0, 100):
            return self._send(ts, wanted)
        if since < self.min_interval_s:
            return None
        if diff >= self.min_step:
            return self._send(ts, wanted)
        if since >= self.settle_s and diff >= self.small_step:
            return self._send(ts, wanted)
        return None

    def _send(self, ts: float, v: int) -> int:
        self.last_sent, self.last_ts = v, ts
        return v


def trvzb_sequence(last: int | None, target: int, bump: int = 10) -> list[int]:
    """Schreibfolge für einen Sonoff TRVZB (Öffnungsgrad in %)."""
    if last is not None and target < last:
        return [min(100, last + bump), target]
    return [target]
