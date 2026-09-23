"""Einrichtung und Einstellungen über die Oberfläche (kein YAML).

Schritt 1: Wohnung (Wetterdienst, Außenfühler, Sonnensensor) – Vorschläge werden automatisch gesucht.
Schritt 2…n: Zonen (Raumsensor, Thermostatköpfe, Fenster, Zeitplan, Heizkörper).
Optionen: Allgemein, Zone hinzufügen / bearbeiten / entfernen, Vorlauffühler nachrüsten.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.util import slugify

from .const import (
    CONF_AREA,
    CONF_AWAY,
    CONF_COMFORT,
    CONF_ECO_DELTA,
    CONF_HEATING_LIMIT,
    CONF_OUTDOOR,
    CONF_RAD_KW,
    CONF_SCHEDULE,
    CONF_SUN,
    CONF_SUPPLY,
    CONF_SUPPLY_ZONE,
    CONF_TEMP,
    CONF_TEMP2,
    CONF_TRVS,
    CONF_WEATHER,
    CONF_WINDOWS,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONF_ZONES,
    DEFAULT_AREA,
    DEFAULT_AWAY,
    DEFAULT_COMFORT,
    DEFAULT_ECO_DELTA,
    DEFAULT_HEATING_LIMIT,
    DEFAULT_RAD_KW,
    DEFAULT_SCHEDULE,
    DOMAIN,
    NAME,
)
from .core.schedule import ScheduleError, WeekSchedule


# ----------------------------------------------------------------------------- Vorschläge
def _suggest(hass: HomeAssistant) -> dict[str, str]:
    """Passende Entities automatisch vorschlagen (nur Vorschlag, alles änderbar)."""
    out: dict[str, str] = {}
    reg = er.async_get(hass)
    weathers = hass.states.async_entity_ids("weather")
    dwd = [w for w in weathers if (e := reg.async_get(w)) and e.platform == "dwd_weather"]
    if dwd or weathers:
        out[CONF_WEATHER] = (dwd or sorted(weathers))[0]
    for st in hass.states.async_all("sensor"):
        dc = st.attributes.get("device_class")
        eid = st.entity_id
        if dc == "illuminance" and CONF_SUN not in out and any(k in eid for k in ("sonne", "sun", "solar")):
            out[CONF_SUN] = eid
        if dc == "temperature" and CONF_OUTDOOR not in out and any(k in eid for k in ("aussen", "außen", "outdoor", "outside")):
            if "helios" not in eid:  # Lüftungs-Ansaugfühler messen zu warm
                out[CONF_OUTDOOR] = eid
    return out


def _general_schema(d: dict) -> vol.Schema:
    def opt(key):
        return vol.Optional(key, description={"suggested_value": d.get(key)})

    return vol.Schema({
        opt(CONF_WEATHER): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
        opt(CONF_OUTDOOR): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
        opt(CONF_SUN): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")),
        vol.Optional(CONF_HEATING_LIMIT, default=d.get(CONF_HEATING_LIMIT, DEFAULT_HEATING_LIMIT)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=22, step=0.5, unit_of_measurement="°C", mode=selector.NumberSelectorMode.BOX)
        ),
    })


def _zone_schema(d: dict) -> vol.Schema:
    def opt(key):
        return vol.Optional(key, description={"suggested_value": d.get(key)})

    def num(key, default, lo, hi, step, unit):
        return (
            vol.Required(key, default=d.get(key, default)),
            selector.NumberSelector(selector.NumberSelectorConfig(min=lo, max=hi, step=step, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX)),
        )

    fields: dict = {
        vol.Required(CONF_ZONE_NAME, default=d.get(CONF_ZONE_NAME, "")): selector.TextSelector(),
        vol.Required(CONF_TEMP, description={"suggested_value": d.get(CONF_TEMP)}): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        opt(CONF_TEMP2): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
        vol.Required(CONF_TRVS, description={"suggested_value": d.get(CONF_TRVS)}): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="climate", multiple=True)
        ),
        opt(CONF_WINDOWS): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)),
    }
    for key, default, lo, hi, step, unit in (
        (CONF_COMFORT, DEFAULT_COMFORT, 15, 26, 0.5, "°C"),
        (CONF_ECO_DELTA, DEFAULT_ECO_DELTA, 0, 6, 0.5, "K"),
        (CONF_AWAY, DEFAULT_AWAY, 10, 20, 0.5, "°C"),
    ):
        k, s = num(key, default, lo, hi, step, unit)
        fields[k] = s
    fields[vol.Required(CONF_SCHEDULE, default=d.get(CONF_SCHEDULE, DEFAULT_SCHEDULE))] = selector.TextSelector()
    for key, default, lo, hi, step, unit in (
        (CONF_RAD_KW, DEFAULT_RAD_KW, 0.2, 10, 0.05, "kW"),
        (CONF_AREA, DEFAULT_AREA, 2, 200, 0.5, "m²"),
    ):
        k, s = num(key, default, lo, hi, step, unit)
        fields[k] = s
    return vol.Schema(fields)


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [])}


def _validate_zone(user: dict, existing: list[dict], editing_id: str | None = None) -> tuple[dict, dict]:
    errors: dict[str, str] = {}
    try:
        WeekSchedule.parse(user.get(CONF_SCHEDULE, ""))
    except ScheduleError:
        errors[CONF_SCHEDULE] = "invalid_schedule"
    name = (user.get(CONF_ZONE_NAME) or "").strip()
    if not name:
        errors[CONF_ZONE_NAME] = "name_required"
    zid = editing_id or slugify(name) or "zone"
    if editing_id is None and any(z[CONF_ZONE_ID] == zid for z in existing):
        errors[CONF_ZONE_NAME] = "name_exists"
    if not user.get(CONF_TRVS):
        errors[CONF_TRVS] = "trv_required"
    zone = _clean({**user, CONF_ZONE_NAME: name, CONF_ZONE_ID: zid})
    return zone, errors


# ----------------------------------------------------------------------------- Einrichtung
class LernendeHeizungConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {CONF_ZONES: []}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data.update(_clean(user_input))
            return await self.async_step_zone()
        return self.async_show_form(step_id="user", data_schema=_general_schema(_suggest(self.hass)))

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zone, errors = _validate_zone(user_input, self._data[CONF_ZONES])
            if not errors:
                self._data[CONF_ZONES].append(zone)
                return await self.async_step_more()
        return self.async_show_form(step_id="zone", data_schema=_zone_schema(user_input or {}), errors=errors)

    async def async_step_more(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="more", menu_options=["zone", "finish"])

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(title=NAME, data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LernendeHeizungOptionsFlow()


# ----------------------------------------------------------------------------- Optionen
class LernendeHeizungOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._opts: dict[str, Any] | None = None
        self._edit: str | None = None

    @property
    def opts(self) -> dict[str, Any]:
        if self._opts is None:
            base = {**self.config_entry.data, **self.config_entry.options}
            base[CONF_ZONES] = [dict(z) for z in base.get(CONF_ZONES, [])]
            self._opts = base
        return self._opts

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["general", "supply", "add_zone"]
        if self.opts[CONF_ZONES]:
            menu += ["edit_zone", "remove_zone"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self.opts)

    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            for k in (CONF_WEATHER, CONF_OUTDOOR, CONF_SUN):
                self.opts.pop(k, None)
            self.opts.update(_clean(user_input))
            return self._save()
        return self.async_show_form(step_id="general", data_schema=_general_schema(self.opts))

    async def async_step_supply(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            for k in (CONF_SUPPLY, CONF_SUPPLY_ZONE):
                self.opts.pop(k, None)
            self.opts.update(_clean(user_input))
            return self._save()
        zones = [selector.SelectOptionDict(value=z[CONF_ZONE_ID], label=z[CONF_ZONE_NAME]) for z in self.opts[CONF_ZONES]]
        schema = vol.Schema({
            vol.Optional(CONF_SUPPLY, description={"suggested_value": self.opts.get(CONF_SUPPLY)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Optional(CONF_SUPPLY_ZONE, description={"suggested_value": self.opts.get(CONF_SUPPLY_ZONE)}): selector.SelectSelector(
                selector.SelectSelectorConfig(options=zones, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })
        return self.async_show_form(step_id="supply", data_schema=schema)

    async def async_step_add_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zone, errors = _validate_zone(user_input, self.opts[CONF_ZONES])
            if not errors:
                self.opts[CONF_ZONES].append(zone)
                return self._save()
        return self.async_show_form(step_id="add_zone", data_schema=_zone_schema(user_input or {}), errors=errors)

    async def async_step_edit_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._edit = user_input["zone"]
            return await self.async_step_zone_form()
        return self.async_show_form(step_id="edit_zone", data_schema=self._zone_pick())

    async def async_step_zone_form(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        idx = next(i for i, z in enumerate(self.opts[CONF_ZONES]) if z[CONF_ZONE_ID] == self._edit)
        if user_input is not None:
            zone, errors = _validate_zone(user_input, self.opts[CONF_ZONES], editing_id=self._edit)
            if not errors:
                self.opts[CONF_ZONES][idx] = zone
                return self._save()
        return self.async_show_form(
            step_id="zone_form", data_schema=_zone_schema(user_input or self.opts[CONF_ZONES][idx]), errors=errors
        )

    async def async_step_remove_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.opts[CONF_ZONES] = [z for z in self.opts[CONF_ZONES] if z[CONF_ZONE_ID] != user_input["zone"]]
            return self._save()
        return self.async_show_form(step_id="remove_zone", data_schema=self._zone_pick())

    def _zone_pick(self) -> vol.Schema:
        opts = [selector.SelectOptionDict(value=z[CONF_ZONE_ID], label=z[CONF_ZONE_NAME]) for z in self.opts[CONF_ZONES]]
        return vol.Schema({vol.Required("zone"): selector.SelectSelector(selector.SelectSelectorConfig(options=opts))})
