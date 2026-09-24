"""Ansteuerung der Thermostatköpfe.

Sonoff TRVZB (Zigbee2MQTT/ZHA): Ventilposition direkt über ``valve_opening_degree`` und
``valve_closing_degree`` (Komplement) – so steht das Ventil unabhängig von der TRV-eigenen Regelung.
Schließen mit kurzem Öffnungs-„Stupser" (Motor verliert sonst gelegentlich die Kalibrierung;
Erfahrung aus Better Thermostat, AGPL-3.0).

Andere Thermostate: grobe An/Aus-Steuerung über die Solltemperatur.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.climate import HVACMode
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .core.actuator import trvzb_sequence

_LOGGER = logging.getLogger(__name__)

_KEYS = {
    "open": ("valve_opening_degree",),
    "close": ("valve_closing_degree",),
    "ext": ("external_temperature_input", "external_temperature"),
    "select": ("temperature_sensor_select", "temperature_sensor"),
}
BUMP_DELAY_S = 5.0


class TrvActuator:
    """Ein Thermostatkopf (climate-Entity) samt zugehöriger Zusatz-Entities."""

    def __init__(self, hass: HomeAssistant, climate_id: str) -> None:
        self.hass = hass
        self.climate_id = climate_id
        self.entities: dict[str, str] = {}
        self.last_pct: int | None = None
        self._pending: asyncio.Task | None = None
        self.resolved = False

    @property
    def kind(self) -> str:
        return "trvzb" if "open" in self.entities else "generic"

    def resolve(self) -> None:
        """Zusatz-Entities desselben Geräts finden (Übersetzungsschlüssel, Unique-ID oder Name)."""
        reg = er.async_get(self.hass)
        ent = reg.async_get(self.climate_id)
        if ent is None or ent.device_id is None:
            self.resolved = True
            return
        found: dict[str, str] = {}
        for e in er.async_entries_for_device(reg, ent.device_id):
            if e.domain not in ("number", "select"):
                continue
            hay = " ".join(x for x in (e.translation_key, e.unique_id, e.entity_id, e.original_name) if x).lower()
            for key, names in _KEYS.items():
                if key == "select" and e.domain != "select":
                    continue
                if key != "select" and e.domain != "number":
                    continue
                if any(n in hay for n in names) and key not in found:
                    found[key] = e.entity_id
        self.entities = found
        self.resolved = True
        _LOGGER.debug("TRV %s: gefunden %s", self.climate_id, found)

    def available(self) -> bool:
        st = self.hass.states.get(self.climate_id)
        return st is not None and st.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    def observed_valve(self) -> float | None:
        """Tatsächliche Ventilstellung (0..1), wenn ein anderer Regler (z. B. BT) den TRV steuert.

        TRVZB: beim Heizen steht das Ventil auf ``valve_opening_degree``, sonst auf
        ``100 − valve_closing_degree``. Andere TRVs: nur an/aus aus ``hvac_action``.
        """
        st = self.hass.states.get(self.climate_id)
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if st.state == HVACMode.OFF:
            return 0.0
        heating = st.attributes.get("hvac_action") == "heating"
        if self.kind == "trvzb":
            key = "open" if heating else "close"
            nst = self.hass.states.get(self.entities[key]) if key in self.entities else None
            try:
                val = float(nst.state) if nst is not None else None
            except ValueError:
                val = None
            if val is None:
                return 1.0 if heating else 0.0
            return val / 100 if heating else max(0.0, 100 - val) / 100
        return 1.0 if heating else 0.0

    async def _number(self, key: str, value: float) -> bool:
        eid = self.entities.get(key)
        if not eid:
            return False
        st = self.hass.states.get(eid)
        if st is not None and st.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                if abs(float(st.state) - value) < 0.05:
                    return True
            except ValueError:
                pass
        await self.hass.services.async_call("number", "set_value", {ATTR_ENTITY_ID: eid, "value": value}, blocking=True)
        return True

    async def take_control(self) -> None:
        """TRV in Heizbetrieb bringen und Regelung auf externen Sensor stellen (einmalig)."""
        if not self.resolved:
            self.resolve()
        st = self.hass.states.get(self.climate_id)
        if st is not None and st.state == HVACMode.OFF:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode", {ATTR_ENTITY_ID: self.climate_id, "hvac_mode": HVACMode.HEAT}, blocking=True
            )
        sel = self.entities.get("select")
        if sel:
            sst = self.hass.states.get(sel)
            opts = (sst.attributes.get("options") if sst else None) or []
            if sst is not None and sst.state != "external" and "external" in opts:
                await self.hass.services.async_call(
                    "select", "select_option", {ATTR_ENTITY_ID: sel, "option": "external"}, blocking=True
                )

    async def set_room_temperature(self, value: float) -> None:
        """Raumtemperatur an den TRV spiegeln (Anzeige am Kopf stimmt dann)."""
        if "ext" in self.entities:
            await self._number("ext", round(value, 1))

    async def set_valve(self, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        if self.kind == "trvzb":
            if self._pending and not self._pending.done():
                self._pending.cancel()
            seq = trvzb_sequence(self.last_pct, pct)
            await self._write_trvzb(seq[0])
            if len(seq) > 1:
                self._pending = self.hass.async_create_background_task(
                    self._delayed(seq[1]), name=f"lernende_heizung_bump_{self.climate_id}"
                )
            self.last_pct = pct
        else:
            # generisch: an/aus über Solltemperatur
            st = self.hass.states.get(self.climate_id)
            max_t = float(st.attributes.get("max_temp", 30)) if st else 30.0
            min_t = float(st.attributes.get("min_temp", 5)) if st else 5.0
            temp = min(max_t, 28.0) if pct >= 30 else max(min_t, 5.0)
            await self.hass.services.async_call(
                "climate", "set_temperature", {ATTR_ENTITY_ID: self.climate_id, "temperature": temp}, blocking=True
            )
            self.last_pct = pct

    async def _write_trvzb(self, pct: int) -> None:
        await self._number("open", pct)
        await self._number("close", 100 - pct)

    async def _delayed(self, pct: int) -> None:
        try:
            await asyncio.sleep(BUMP_DELAY_S)
            await self._write_trvzb(pct)
        except asyncio.CancelledError:
            return

    async def release(self, fallback_temp: float) -> None:
        """Kontrolle zurückgeben: TRV regelt wieder selbst – mit dem eingebauten Fühler, denn den
        externen Wert schreibt danach niemand mehr (der TRV würde auf einen eingefrorenen Wert regeln)."""
        if self._pending and not self._pending.done():
            self._pending.cancel()
        if self.kind == "trvzb":
            await self._number("open", 100)
            await self._number("close", 100)
        sel = self.entities.get("select")
        sst = self.hass.states.get(sel) if sel else None
        if sst is not None and sst.state != "internal" and "internal" in (sst.attributes.get("options") or []):
            await self.hass.services.async_call(
                "select", "select_option", {ATTR_ENTITY_ID: sel, "option": "internal"}, blocking=True
            )
        await self.hass.services.async_call(
            "climate", "set_temperature", {ATTR_ENTITY_ID: self.climate_id, "temperature": fallback_temp}, blocking=True
        )
        self.last_pct = None
