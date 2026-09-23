"""Aufbereitung der Eingangssignale: Außentemperatur-Fusion, Sonne, Raumsensor-Filter, Vorlauf.

- Außen: Wetterdienst (z. B. DWD) ist genau, aber träge/geglättet; ein lokaler Fühler reagiert
  schnell, misst aber oft zu warm (Hauswand, Dach, Sonne). Wir lernen den Versatz des lokalen
  Fühlers je Tagesstunde und mitteln beide.
- Sonne: Lux-Sensor → grobe Globalstrahlung (kW/m²); Vorhersage aus Sonnenstand × Bewölkung,
  auf den Sensor kalibriert.
- Raumsensor: kurze Sonnenspitzen direkt auf dem Sensor (Wohnzimmer, Dez–Feb bis 30 °C) werden
  per Zweitsensor oder Anstiegsbegrenzung ersetzt.
- Vorlauf: Fühler am Heizkörperanschluss zeigt nur bei offenem Ventil den Vorlauf → nur dann lernen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import math


# ----------------------------------------------------------------------------- Außen
@dataclass
class OutdoorFusion:
    bias: list[float] = field(default_factory=lambda: [0.0] * 24)
    count: list[int] = field(default_factory=lambda: [0] * 24)
    alpha: float = 0.05
    last: float | None = None

    def update(self, hour: int, weather: float | None, local: float | None) -> float | None:
        if weather is not None and local is not None:
            e = local - weather
            if abs(e) < 15:
                c = self.count[hour]
                a = max(self.alpha, 1.0 / (c + 1))
                self.bias[hour] += a * (e - self.bias[hour])
                self.count[hour] = c + 1
            corr = local - self.bias[hour]
            self.last = 0.5 * weather + 0.5 * corr if self.count[hour] >= 10 else weather
        elif weather is not None:
            self.last = weather
        elif local is not None:
            self.last = local - (self.bias[hour] if self.count[hour] >= 10 else 0.0)
        return self.last

    def export(self) -> dict:
        return {"bias": self.bias, "count": self.count}

    def restore(self, raw: dict) -> None:
        b, c = raw.get("bias"), raw.get("count")
        if isinstance(b, list) and isinstance(c, list) and len(b) == 24 == len(c):
            self.bias = [float(x) for x in b]
            self.count = [int(x) for x in c]


# ----------------------------------------------------------------------------- Sonne
def sun_position(ts: float, lat: float, lon: float) -> tuple[float, float]:
    """(Elevation, Azimut) in Grad, NOAA-Näherung."""
    n = ts / 86400.0 + 2440587.5 - 2451545.0
    L = (280.46 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.02 * math.sin(2 * g))
    eps = math.radians(23.439 - 4e-7 * n)
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    ha = math.radians(gmst * 15 + lon) - ra
    la = math.radians(lat)
    el = math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha), math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(ha))
    return math.degrees(el), (math.degrees(az) + 360) % 360


def clear_sky_ghi(elev_deg: float) -> float:
    """Globalstrahlung bei klarem Himmel (kW/m², Haurwitz)."""
    if elev_deg <= 0:
        return 0.0
    s = math.sin(math.radians(elev_deg))
    return 1.098 * s * math.exp(-0.057 / s)


FACADES = (90.0, 180.0, 270.0)  # Ost, Süd, West


def beam_normal_clear(elev_deg: float) -> float:
    """Direktnormalstrahlung bei klarem Himmel (kW/m², Meinel)."""
    if elev_deg <= 1:
        return 0.0
    am = 1 / math.sin(math.radians(elev_deg))
    return 1.0 * 0.7 ** (am ** 0.678)


@dataclass
class SunModel:
    """Sonne auf Ost-/Süd-/Westfassade (kW/m²) aus Sonnenstand × Klarheit.

    Klarheit kommt vom Lux-Sensor (gemessen/klarer Himmel, obere Hüllkurve kalibriert) oder aus der
    Bewölkungsvorhersage. Die Fensterausrichtung muss niemand angeben – das Lernen gewichtet die
    drei Fassaden selbst.
    """

    lat: float
    lon: float
    lux_per_kw: float = 110000.0
    scale: float = 1.0  # obere Hüllkurve Sensor/klarer Himmel (Sensor evtl. verschattet/geneigt)
    n: int = 0

    def ghi_from_lux(self, lux: float | None) -> float | None:
        if lux is None or not math.isfinite(lux) or lux < 0:
            return None
        return min(1.3, lux / self.lux_per_kw)

    def clearness(self, ts: float, ghi_meas: float | None, cloud_pct: float | None) -> float:
        el, _ = sun_position(ts, self.lat, self.lon)
        cs = clear_sky_ghi(el)
        if ghi_meas is not None and cs > 0.05:
            ratio = ghi_meas / cs
            if el > 10:
                self.n += 1
                # obere Hüllkurve: schnell hoch, langsam runter
                self.scale += (0.05 if ratio > self.scale else 0.002) * (ratio - self.scale)
                self.scale = min(3.0, max(0.1, self.scale))
            return min(1.2, max(0.0, ratio / max(self.scale, 0.1)))
        cc = 0.6 if cloud_pct is None else min(1.0, max(0.0, cloud_pct / 100))
        return 1 - 0.75 * cc ** 3.4

    def facades(self, ts: float, clearness: float) -> tuple[float, float, float]:
        el, az = sun_position(ts, self.lat, self.lon)
        bn = beam_normal_clear(el) * min(1.0, max(0.0, (clearness - 0.25) / 0.75))
        ce = math.cos(math.radians(el))
        return tuple(bn * max(0.0, ce * math.cos(math.radians(az - f))) for f in FACADES)  # type: ignore[return-value]

    def ghi(self, ts: float, clearness: float) -> float:
        el, _ = sun_position(ts, self.lat, self.lon)
        return clear_sky_ghi(el) * clearness


# ----------------------------------------------------------------------------- Raumsensor
@dataclass
class RoomSensorFilter:
    """Ersetzt unplausible Spitzen des Hauptsensors (z. B. direkte Sonne)."""

    max_rise_kph: float = 1.5  # schneller kann der Raum nicht wärmer werden
    max_offset: float = 1.0  # K Abweichung zum Zweitsensor
    offset: float = 0.0  # gelernter üblicher Abstand Haupt − Zweitsensor
    n: int = 0
    last_ok: float | None = None
    last_ts: float | None = None
    disturbed: bool = False

    def update(self, ts: float, primary: float | None, secondary: float | None) -> float | None:
        if primary is None:
            self.disturbed = False
            return None if secondary is None else secondary + self.offset
        spike = False
        if secondary is not None:
            d = primary - secondary
            if self.n >= 30 and d - self.offset > self.max_offset:
                spike = True
            elif not spike:
                self.n += 1
                a = max(0.002, 1.0 / self.n)
                self.offset += a * (d - self.offset)
        if self.last_ok is not None and self.last_ts is not None:
            dt = (ts - self.last_ts) / 3600.0
            if 0 < dt < 1 and primary - self.last_ok > self.max_rise_kph * dt + 0.3:
                spike = True
        self.disturbed = spike
        if spike:
            val = secondary + self.offset if secondary is not None else self.last_ok
        else:
            val = primary
            self.last_ok, self.last_ts = primary, ts
        return val


# ----------------------------------------------------------------------------- Vorlauf
@dataclass
class SupplyLearner:
    """Heizkurve aus einem Rohrfühler am Heizkörper: lernt Tvl = a + b·Tout bei offenem Ventil."""

    a: float = 47.0
    b: float = -0.8
    n: int = 0
    open_since: float | None = None
    _sxx: float = 0.0
    _sx: float = 0.0
    _sy: float = 0.0
    _sxy: float = 0.0
    _w: float = 0.0

    def update(self, ts: float, pipe: float | None, t_out: float | None, valve: float, pipe_offset: float = 2.0) -> None:
        if pipe is None or t_out is None:
            return
        if valve < 0.3:
            self.open_since = None
            return
        if self.open_since is None:
            self.open_since = ts
            return
        if ts - self.open_since < 20 * 60:
            return
        y = pipe + pipe_offset
        lam = 0.999
        self._w = lam * self._w + 1
        self._sx = lam * self._sx + t_out
        self._sy = lam * self._sy + y
        self._sxx = lam * self._sxx + t_out * t_out
        self._sxy = lam * self._sxy + t_out * y
        self.n += 1
        den = self._w * self._sxx - self._sx ** 2
        if self.n >= 30 and den > 1e-6 * self._w ** 2 and den / self._w ** 2 > 4.0:  # Tout-Spreizung > 2 K
            self.b = (self._w * self._sxy - self._sx * self._sy) / den
            self.a = (self._sy - self.b * self._sx) / self._w
        elif self.n >= 10:
            # nur Niveau anpassen
            self.a = self._sy / self._w - self.b * self._sx / self._w

    def supply(self, t_out: float) -> float:
        return min(75.0, max(25.0, self.a + self.b * t_out))

    def export(self) -> dict:
        return {k: getattr(self, k) for k in ("a", "b", "n", "_sxx", "_sx", "_sy", "_sxy", "_w")}

    def restore(self, raw: dict) -> None:
        for k, v in raw.items():
            if hasattr(self, k) and isinstance(v, (int, float)) and math.isfinite(v):
                setattr(self, k, type(getattr(self, k))(v))


def utc_hour(ts: float) -> int:
    return datetime.fromtimestamp(ts, UTC).hour
