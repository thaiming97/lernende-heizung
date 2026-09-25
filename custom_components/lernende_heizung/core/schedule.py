"""Wochenzeitplan: Komfortzeiten als Text, z. B. ``Mo-Fr 06:00-08:00, 16:30-22:00; Sa-So 07:30-22:30``.

Außerhalb der Komfortzeiten gilt die Absenktemperatur. Mitternacht-übergreifende Zeiten
(``22:00-02:00``) sind erlaubt. ``immer`` = durchgehend Komfort.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

DAYS = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_RANGE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


class ScheduleError(ValueError):
    """Zeitplan-Text ist ungültig."""


@dataclass(frozen=True)
class WeekSchedule:
    # je Wochentag Liste von (start_min, end_min) in Minuten ab 0:00; end kann > 1440 sein
    slots: tuple[tuple[tuple[int, int], ...], ...]
    text: str

    @classmethod
    def parse(cls, text: str) -> WeekSchedule:
        raw = (text or "").strip()
        days: list[list[tuple[int, int]]] = [[] for _ in range(7)]
        if raw.lower() in ("immer", "always", "24/7"):
            return cls(tuple(((0, 1440),) for _ in range(7)), raw)
        if not raw:
            raise ScheduleError("leer")
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^([A-Za-zäÄ,\-\s]+?)\s+(\d.*)$", part)
            if not m:
                raise ScheduleError(f"Tage fehlen: {part}")
            day_set = _parse_days(m.group(1))
            for rng in m.group(2).split(","):
                r = _RANGE.match(rng.strip())
                if not r:
                    raise ScheduleError(f"Zeit ungültig: {rng.strip()}")
                h1, m1, h2, m2 = map(int, r.groups())
                if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
                    raise ScheduleError(f"Zeit ungültig: {rng.strip()}")
                a, b = h1 * 60 + m1, h2 * 60 + m2
                if b <= a:
                    b += 1440
                for d in day_set:
                    days[d].append((a, b))
        return cls(tuple(tuple(sorted(d)) for d in days), raw)

    def is_comfort(self, when: datetime) -> bool:
        minute = when.hour * 60 + when.minute
        wd = when.weekday()
        for a, b in self.slots[wd]:
            if a <= minute < b:
                return True
        # Vortag über Mitternacht
        prev = self.slots[(wd - 1) % 7]
        return any(b > 1440 and minute < b - 1440 for _, b in prev)

    def next_change(self, when: datetime, limit_h: int = 8 * 24) -> datetime | None:
        """Nächster Wechsel Komfort↔Absenkung (Minutenraster, max. limit_h)."""
        cur = self.is_comfort(when)
        t = when.replace(second=0, microsecond=0)
        # grob in 15-min-Schritten, dann minutengenau
        for _ in range(limit_h * 4):
            t2 = t + timedelta(minutes=15)
            if self.is_comfort(t2) != cur:
                for k in range(1, 16):
                    t3 = t + timedelta(minutes=k)
                    if self.is_comfort(t3) != cur:
                        return t3
            t = t2
        return None


def _parse_days(s: str) -> set[int]:
    out: set[int] = set()
    for tok in s.replace(" ", "").lower().split(","):
        if not tok:
            continue
        if tok in ("täglich", "taeglich", "daily", "alle"):
            return set(range(7))
        if "-" in tok:
            a, b = tok.split("-", 1)
            ia, ib = _day(a, tok), _day(b, tok)
            k = ia
            while True:
                out.add(k)
                if k == ib:
                    break
                k = (k + 1) % 7
        else:
            out.add(_day(tok, tok))
    return out


def _day(name: str, tok: str) -> int:
    """Wochentag aus deutschem (Mo, Montag) oder englischem Namen (Tue, Tuesday)."""
    for key in (name[:3], name[:2]):
        if key in DAYS:
            return DAYS[key]
    raise ScheduleError(f"Tag unbekannt: {tok}")


def local_dt(ts: float, tz: str) -> datetime:
    return datetime.fromtimestamp(ts, ZoneInfo(tz))
