"""Tests der Home-Assistant-Integration (Config Flow, Entities, Ventilansteuerung)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.lernende_heizung import trv as trv_mod
from custom_components.lernende_heizung.const import (
    CONF_AREA,
    CONF_AWAY,
    CONF_COMFORT,
    CONF_ECO_DELTA,
    CONF_RAD_KW,
    CONF_OUTDOOR,
    CONF_SCHEDULE,
    CONF_SOFI,
    CONF_SUPPLY,
    CONF_SUPPLY_ZONE,
    CONF_TEMP,
    CONF_TRVS,
    CONF_WINDOWS,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    CONF_ZONES,
    DOMAIN,
    SENSOR_STALE_S,
)
from custom_components.lernende_heizung.coordinator import _num
from custom_components.lernende_heizung.diagnostics import async_get_config_entry_diagnostics

ZONE = {
    CONF_ZONE_ID: "bad", CONF_ZONE_NAME: "Bad", CONF_TEMP: "sensor.bad_temp", CONF_TRVS: ["climate.bad"],
    CONF_WINDOWS: ["binary_sensor.fenster_bad"], CONF_COMFORT: 23.5, CONF_ECO_DELTA: 2.0, CONF_AWAY: 17.0,
    CONF_SCHEDULE: "immer", CONF_RAD_KW: 0.65, CONF_AREA: 7.3,
}


def _trv(hass: HomeAssistant, name: str) -> None:
    """Sonoff-TRVZB-Gerät wie von Zigbee2MQTT angelegt."""
    mqtt = MockConfigEntry(domain="mqtt")
    mqtt.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=mqtt.entry_id, identifiers={("mqtt", name)}, name=name)
    reg = er.async_get(hass)
    reg.async_get_or_create("climate", "mqtt", f"{name}_climate", device_id=dev.id, suggested_object_id=name, config_entry=mqtt)
    for key in ("valve_opening_degree", "valve_closing_degree", "external_temperature_input"):
        reg.async_get_or_create("number", "mqtt", f"{name}_{key}", device_id=dev.id, suggested_object_id=f"{name}_{key}", config_entry=mqtt)
        hass.states.async_set(f"number.{name}_{key}", "50")
    reg.async_get_or_create("select", "mqtt", f"{name}_temperature_sensor_select", device_id=dev.id,
                            suggested_object_id=f"{name}_temperature_sensor_select", config_entry=mqtt)
    hass.states.async_set(f"select.{name}_temperature_sensor_select", "internal", {"options": ["internal", "external"]})
    hass.states.async_set(f"climate.{name}", "heat", {"min_temp": 4, "max_temp": 35})


def _eid(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    _trv(hass, "bad")
    hass.states.async_set("sensor.bad_temp", "20.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("binary_sensor.fenster_bad", "off")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={CONF_ZONES: [ZONE]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ----------------------------------------------------------------------------- Config Flow
async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.sonnensensor_illuminance", "1000", {"device_class": "illuminance"})
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["step_id"] == "zone"
    zone_in = {k: v for k, v in ZONE.items() if k != CONF_ZONE_ID}
    bad = await hass.config_entries.flow.async_configure(r["flow_id"], {**zone_in, CONF_SCHEDULE: "Montag früh"})
    assert bad["errors"] == {CONF_SCHEDULE: "invalid_schedule"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], zone_in)
    assert r["type"] is FlowResultType.MENU
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "finish"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["data"][CONF_ZONES][0][CONF_ZONE_ID] == "bad"


async def test_options_add_and_remove_zone(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    _trv(hass, "schlafzimmer")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "add_zone"})
    new = {**{k: v for k, v in ZONE.items() if k != CONF_ZONE_ID}, CONF_ZONE_NAME: "Schlafen", CONF_TRVS: ["climate.schlafzimmer"]}
    r = await hass.config_entries.options.async_configure(r["flow_id"], new)
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert [z[CONF_ZONE_ID] for z in entry.options[CONF_ZONES]] == ["bad", "schlafen"]
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "remove_zone"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"zone": "bad"})
    await hass.async_block_till_done()
    assert [z[CONF_ZONE_ID] for z in entry.options[CONF_ZONES]] == ["schlafen"]


# ----------------------------------------------------------------------------- Laufzeit
async def test_observe_then_control_window_and_master(hass: HomeAssistant, freezer) -> None:
    calls = async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        coord = entry.runtime_data
        # Dienste der Fremd-Plattformen erst nach dem Setup ersetzen (Setup lädt climate/select selbst)
        async_mock_service(hass, "climate", "set_hvac_mode")
        temp_calls = async_mock_service(hass, "climate", "set_temperature")
        sel_calls = async_mock_service(hass, "select", "select_option")
        # Beobachtungsmodus: nichts wird geschrieben
        assert calls == []
        status = hass.states.get(_eid(hass, entry, "sensor", "bad_status"))
        assert status.state == "beobachten"
        climate = hass.states.get(_eid(hass, entry, "climate", "bad_climate"))
        assert climate.attributes["temperature"] == 23.5

        # Zone aktiv schalten → Ventil wird gestellt (20 °C bei Ziel 23,5 → öffnen)
        await hass.services.async_call("switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "bad_active")}, blocking=True)
        await hass.async_block_till_done()
        opened = {c.data["entity_id"]: c.data["value"] for c in calls}
        assert opened["number.bad_valve_opening_degree"] > 0
        assert opened["number.bad_valve_opening_degree"] + opened["number.bad_valve_closing_degree"] == 100
        assert any(c.data["option"] == "external" for c in sel_calls)
        assert coord.zones["bad"].controlled

        # Fenster auf → nach 1 min zu
        calls.clear()
        hass.states.async_set("binary_sensor.fenster_bad", "on")
        freezer.tick(timedelta(seconds=61))
        await coord.async_refresh()
        await hass.async_block_till_done()
        last = {c.data["entity_id"]: c.data["value"] for c in calls}
        assert last["number.bad_valve_opening_degree"] == 0
        assert hass.states.get(_eid(hass, entry, "sensor", "bad_status")).state == "fenster"

        # Hauptschalter aus → TRV bekommt die Kontrolle zurück (mit eigenem Fühler)
        calls.clear()
        hass.states.async_set("select.bad_temperature_sensor_select", "external", {"options": ["internal", "external"]})
        await hass.services.async_call("switch", "turn_off", {"entity_id": _eid(hass, entry, "switch", "master")}, blocking=True)
        await hass.async_block_till_done()
        last = {c.data["entity_id"]: c.data["value"] for c in calls}
        assert last["number.bad_valve_opening_degree"] == 100 and last["number.bad_valve_closing_degree"] == 100
        assert temp_calls and not coord.zones["bad"].controlled
        assert sel_calls[-1].data["option"] == "internal"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def _activate(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.services.async_call("switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "bad_active")}, blocking=True)
    await hass.async_block_till_done()


async def _tick(hass: HomeAssistant, freezer, coord, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    hass.states.async_set("sensor.bad_temp", "20.0", {"unit_of_measurement": "°C", "device_class": "temperature"},
                          force_update=True)
    await coord.async_refresh()
    await hass.async_block_till_done()


async def test_window_counts_only_after_one_minute(hass: HomeAssistant, freezer) -> None:
    """Kurz rausgehen (Tür < 1 min offen): Ventil bleibt, Lernen läuft weiter. Erst ab 1 min gilt sie als offen."""
    calls = async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        coord = entry.runtime_data
        async_mock_service(hass, "climate", "set_hvac_mode")
        async_mock_service(hass, "select", "select_option")
        await _activate(hass, entry)
        z = coord.zones["bad"]
        opened = z.valve_pct
        assert opened > 0
        calls.clear()
        hass.states.async_set("binary_sensor.fenster_bad", "on")
        await _tick(hass, freezer, coord, 20)
        assert not z.window_open and z.valve_pct == opened
        assert not any(c.data["value"] == 0 and "opening" in c.data["entity_id"] for c in calls)
        hass.states.async_set("binary_sensor.fenster_bad", "off")
        await _tick(hass, freezer, coord, 20)
        assert z.learner.blocked_until < dt_util.utcnow().timestamp()  # kein Lernstopp
        # diesmal länger offen: nach 1 min (Timer, kein Regeltakt nötig) → zu
        hass.states.async_set("binary_sensor.fenster_bad", "on")
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=65))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert z.window_open and z.valve_pct == 0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_valve_stays_closed_15_min_after_window(hass: HomeAssistant, freezer) -> None:
    """Nach dem Lüften wärmt sich die Luft aus Wänden und Möbeln selbst wieder auf – sofort heizen
    überheizt. Deshalb 15 min zu lassen, danach sofort wieder regeln (nicht auf den Ventil-Takt warten)."""
    async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        coord = entry.runtime_data
        async_mock_service(hass, "climate", "set_hvac_mode")
        async_mock_service(hass, "select", "select_option")
        await _activate(hass, entry)
        z = coord.zones["bad"]
        hass.states.async_set("binary_sensor.fenster_bad", "on")
        await _tick(hass, freezer, coord, 120)
        assert z.valve_pct == 0
        hass.states.async_set("binary_sensor.fenster_bad", "off")
        await _tick(hass, freezer, coord, 5)
        for _ in range(2):  # 10 min nach dem Schließen: noch zu
            await _tick(hass, freezer, coord, 300)
            assert z.valve_pct == 0 and z.decision.reason == "fenster"
        assert "Nach dem Lüften" in hass.states.get("sensor.bad_erklaerung_lh").state
        await _tick(hass, freezer, coord, 360)  # > 15 min
        assert z.decision.reason != "fenster" and z.valve_pct > 0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_new_zigbee2mqtt_sensor_names(hass: HomeAssistant) -> None:
    """Zigbee2MQTT nennt die Fühlerwahl inzwischen local_temperature/remote_temperature."""
    async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        opts = {"options": ["local_temperature", "remote_temperature", "remote_source_offline"]}
        hass.states.async_set("select.bad_temperature_sensor_select", "local_temperature", opts)
        async_mock_service(hass, "climate", "set_hvac_mode")
        async_mock_service(hass, "climate", "set_temperature")
        sel_calls = async_mock_service(hass, "select", "select_option")
        await _activate(hass, entry)
        assert [c.data["option"] for c in sel_calls] == ["remote_temperature"]
        hass.states.async_set("select.bad_temperature_sensor_select", "remote_temperature", opts)
        await hass.services.async_call("switch", "turn_off", {"entity_id": _eid(hass, entry, "switch", "master")}, blocking=True)
        await hass.async_block_till_done()
        assert sel_calls[-1].data["option"] == "local_temperature"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_room_temperature_resent_every_30_min(hass: HomeAssistant, freezer) -> None:
    """Der Kopf soll den externen Fühler nicht für ausgefallen halten, nur weil die Temperatur gleich bleibt."""
    calls = async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        coord = entry.runtime_data
        async_mock_service(hass, "climate", "set_hvac_mode")
        async_mock_service(hass, "select", "select_option")
        await _activate(hass, entry)
        ext = "number.bad_external_temperature_input"
        hass.states.async_set(ext, "20.0")  # Kopf hat den Wert übernommen
        calls.clear()
        await _tick(hass, freezer, coord, 600)
        assert not [c for c in calls if c.data["entity_id"] == ext]
        for _ in range(4):
            await _tick(hass, freezer, coord, 300)
        assert [c for c in calls if c.data["entity_id"] == ext]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_explanation_shows_commanded_valve(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        async_mock_service(hass, "climate", "set_hvac_mode")
        async_mock_service(hass, "select", "select_option")
        await _activate(hass, entry)
        z = entry.runtime_data.zones["bad"]
        assert f"Ventil {z.valve_pct} %" in hass.states.get("sensor.bad_erklaerung_lh").state
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_learning_pause_names_real_reason(hass: HomeAssistant) -> None:
    """Nach Sommer → Winter stand „Fenster war gerade offen“, obwohl kein Fenster offen war."""
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    coord = entry.runtime_data
    season = {"entity_id": _eid(hass, entry, "select", "season")}
    await hass.services.async_call("select", "select_option", {**season, "option": "sommer"}, blocking=True)
    await hass.services.async_call("select", "select_option", {**season, "option": "winter"}, blocking=True)
    await hass.async_block_till_done()
    assert coord.heating_season
    pause = hass.states.get("sensor.bad_erklaerung_lh").attributes["lernpause"]
    assert pause and "Fenster" not in pause
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_cold_pipe_pauses_learning(hass: HomeAssistant, freezer) -> None:
    """Ventil offen, Rohrfühler bleibt kalt → unklar, ob Wärme ankommt → nicht lernen (sonst hielte das
    Modell die Heizkörper für schwach). Ein Fühler, der nie Vorlauf gezeigt hat, meldet keinen kalten Kessel."""
    async_mock_service(hass, "number", "set_value")
    _trv(hass, "bad")
    hass.states.async_set("climate.bad", "heat", {"hvac_action": "heating", "min_temp": 4, "max_temp": 35})
    hass.states.async_set("number.bad_valve_opening_degree", "80")
    hass.states.async_set("sensor.bad_temp", "20.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("binary_sensor.fenster_bad", "off")
    hass.states.async_set("sensor.rohr", "20.5", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("sensor.aussen", "2.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN,
                            data={CONF_ZONES: [ZONE], CONF_SUPPLY: "sensor.rohr", CONF_SUPPLY_ZONE: "bad",
                                  CONF_OUTDOOR: "sensor.aussen"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    for _ in range(12):  # 60 min
        freezer.tick(timedelta(minutes=5))
        for eid, val in (("sensor.rohr", "20.5"), ("sensor.bad_temp", "20.0")):
            hass.states.async_set(eid, val, {"unit_of_measurement": "°C", "device_class": "temperature"}, force_update=True)
        await coord.async_refresh()
        await hass.async_block_till_done()
    assert coord.zones["bad"].learner.samples <= 1  # nur die Viertelstunde, bevor das Rohr als kalt gilt
    # pausiert, aber Speichermasse/Heizkörper laufen weiter (sonst stimmen sie nach der Pause nicht)
    assert coord.zones["bad"].learner.last_ts == dt_util.utcnow().timestamp()
    expl = hass.states.get("sensor.bad_erklaerung_lh")
    assert "Rohr" in expl.attributes["lernpause"]
    assert not coord.supply.heat_missing(dt_util.utcnow().timestamp())
    assert "Fühler" in hass.states.get("sensor.vorlauf_lh").attributes["rohrfuehler_status"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_preset_ends_manual_heat_mode(hass: HomeAssistant) -> None:
    """Im Modus „Heizen“ hatte die Wahl Komfort/Eco/Weg keine Wirkung – jetzt geht es zurück auf Automatik."""
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    cid = _eid(hass, entry, "climate", "bad_climate")
    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": cid, "hvac_mode": "heat"}, blocking=True)
    await hass.services.async_call("climate", "set_temperature", {"entity_id": cid, "temperature": 20.0}, blocking=True)
    await hass.services.async_call("climate", "set_preset_mode", {"entity_id": cid, "preset_mode": "eco"}, blocking=True)
    await hass.async_block_till_done()
    st = hass.states.get(cid)
    assert st.state == "auto" and st.attributes["temperature"] == 21.5
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_temperature_change_lasts_without_schedule_change(hass: HomeAssistant, freezer) -> None:
    """Zeitplan „immer“: Es gibt keinen Wechsel, an dem die Änderung enden könnte – vorher fiel sie nach
    4 h stillschweigend zurück. Jetzt bleibt sie (auch über einen Neustart) bis Preset/Modus/Anwesenheit."""
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    cid = _eid(hass, entry, "climate", "bad_climate")
    await hass.services.async_call("climate", "set_temperature", {"entity_id": cid, "temperature": 22.0}, blocking=True)
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=5))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 22.0
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 22.0
    await hass.services.async_call("climate", "set_preset_mode", {"entity_id": cid, "preset_mode": "none"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 23.5
    assert await hass.config_entries.async_unload(entry.entry_id)


SCHLAFEN = {
    CONF_ZONE_ID: "schlafen", CONF_ZONE_NAME: "Schlafen", CONF_TEMP: "sensor.schlafen_temp", CONF_TRVS: ["climate.schlafzimmer"],
    CONF_WINDOWS: [], CONF_COMFORT: 21.0, CONF_ECO_DELTA: 2.0, CONF_AWAY: 17.0, CONF_SCHEDULE: "immer",
    CONF_RAD_KW: 1.35, CONF_AREA: 18.5,
}


async def _setup_sofi(hass: HomeAssistant) -> MockConfigEntry:
    """Bad mit Sofi-Temperatur 25 °C, Schlafen ohne (bleibt wie immer)."""
    _trv(hass, "bad")
    _trv(hass, "schlafzimmer")
    for eid in ("sensor.bad_temp", "sensor.schlafen_temp"):
        hass.states.async_set(eid, "20.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("binary_sensor.fenster_bad", "off")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={CONF_ZONES: [{**ZONE, CONF_SOFI: 25.0}, SCHLAFEN]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_sofi_mode(hass: HomeAssistant) -> None:
    """Sofi-Modus an: gewählte Räume auf ihre Sofi-Temperatur (Absenkung im gleichen Abstand), andere bleiben.
    Sofi gewinnt über Abwesend/Urlaub (sie ist ja da); „Heizen“ (feste Temperatur) bleibt. Aus → wie vorher."""
    async_mock_service(hass, "number", "set_value")
    entry = await _setup_sofi(hass)
    bad, schlafen = "climate.bad_lh", "climate.schlafen_lh"
    sofi = {"entity_id": "switch.sofi_lh"}

    def soll(eid: str) -> float:
        return hass.states.get(eid).attributes["temperature"]

    async def call(domain: str, service: str, data: dict) -> None:
        await hass.services.async_call(domain, service, data, blocking=True)
        await hass.async_block_till_done()

    assert (soll(bad), soll(schlafen)) == (23.5, 21.0)
    await call("switch", "turn_on", sofi)
    assert hass.states.get("switch.sofi_lh").state == "on"
    assert (soll(bad), soll(schlafen)) == (25.0, 21.0)
    assert hass.states.get(bad).attributes["sofi"] is True and "sofi" not in hass.states.get(schlafen).attributes
    assert "Sofi" in hass.states.get("sensor.bad_erklaerung_lh").state
    await call("climate", "set_preset_mode", {"entity_id": bad, "preset_mode": "eco"})
    assert soll(bad) == 23.0
    await call("climate", "set_preset_mode", {"entity_id": bad, "preset_mode": "none"})
    # Abwesend: Sofi-Räume bleiben warm, die anderen senken ab
    await call("select", "select_option", {"entity_id": "select.anwesenheit_lh", "option": "abwesend"})
    assert (soll(bad), soll(schlafen)) == (25.0, 17.0)
    await call("switch", "turn_off", sofi)
    assert (soll(bad), soll(schlafen)) == (17.0, 17.0)
    await call("select", "select_option", {"entity_id": "select.anwesenheit_lh", "option": "zuhause"})
    # von Hand verstellte Temperatur endet mit dem Umschalten (neue Situation), „Heizen“ bleibt
    await call("climate", "set_temperature", {"entity_id": bad, "temperature": 24.0})
    await call("switch", "turn_on", sofi)
    assert soll(bad) == 25.0
    await call("climate", "set_hvac_mode", {"entity_id": bad, "hvac_mode": "heat"})
    await call("climate", "set_temperature", {"entity_id": bad, "temperature": 20.0})
    await call("switch", "turn_off", sofi)
    await call("switch", "turn_on", sofi)
    assert soll(bad) == 20.0
    # übersteht einen Neustart
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.sofi_lh").state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_sofi_temperature_in_zone_settings(hass: HomeAssistant) -> None:
    """Sofi-Temperatur wird je Zone unter „Zone bearbeiten“ eingestellt; leer = Raum bleibt wie immer."""
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "edit_zone"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"zone": "bad"})
    assert CONF_SOFI in r["data_schema"].schema
    form = {k: v for k, v in ZONE.items() if k != CONF_ZONE_ID}
    r = await hass.config_entries.options.async_configure(r["flow_id"], {**form, CONF_SOFI: 24.5})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_ZONES][0][CONF_SOFI] == 24.5
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_climate_modes_and_override(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    cid = _eid(hass, entry, "climate", "bad_climate")
    await hass.services.async_call("climate", "set_temperature", {"entity_id": cid, "temperature": 22.0}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 22.0
    await hass.services.async_call("climate", "set_preset_mode", {"entity_id": cid, "preset_mode": "eco"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 21.5
    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": cid, "hvac_mode": "off"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(cid).state == "off"
    # Anwesenheit „abwesend" → Abwesenheitstemperatur
    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": cid, "hvac_mode": "auto"}, blocking=True)
    await hass.services.async_call("climate", "set_preset_mode", {"entity_id": cid, "preset_mode": "none"}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": _eid(hass, entry, "select", "presence"), "option": "abwesend"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 17.0


async def test_state_survives_restart(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    coord = entry.runtime_data
    coord.zones["bad"].active = True
    coord.zones["bad"].energy_kwh = 12.5
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    z = entry.runtime_data.zones["bad"]
    assert z.active and z.energy_kwh >= 12.5

async def test_learned_state_saved_while_running(hass: HomeAssistant, hass_storage, freezer) -> None:
    """Bisher wurde im 5-min-Takt „verzögert gespeichert“ – HA verschob den Termin jedes Mal, geschrieben
    wurde nur beim Beenden. Jetzt landet der Stand auch ohne Neustart regelmäßig auf der Platte."""
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    coord = entry.runtime_data
    key = f"{DOMAIN}.{entry.entry_id}"
    coord.zones["bad"].energy_kwh = 4.2
    for _ in range(4):  # 20 min Regeltakt
        freezer.tick(timedelta(minutes=5))
        await coord.async_refresh()
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    assert hass_storage[key]["data"]["zones"]["bad"]["energy_kwh"] >= 4.2
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_trv_switched_off_is_taken_back(hass: HomeAssistant) -> None:
    """Kopf wird während der Regelung ausgeschaltet → sofort wieder Heizen, Problem, Lernpause."""
    async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        coord = entry.runtime_data
        hvac_calls = async_mock_service(hass, "climate", "set_hvac_mode")
        hass.states.async_set("select.bad_temperature_sensor_select", "external", {"options": ["internal", "external"]})
        await hass.services.async_call("switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "bad_active")}, blocking=True)
        await hass.async_block_till_done()
        assert hvac_calls == []  # stand schon auf Heizen
        hass.states.async_set("climate.bad", "off", {"min_temp": 4, "max_temp": 35})
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert [c.data["hvac_mode"] for c in hvac_calls] == ["heat"]
        probs = hass.states.get("binary_sensor.bad_problem_lh").attributes["probleme"]
        assert any("Aus" in p for p in probs)
        assert coord.zones["bad"].valve_frac is None  # Stellung unsicher → nicht lernen
        # übernimmt der Kopf nicht, wird nicht bei jedem Takt erneut geschrieben
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert len(hvac_calls) == 1
        # wieder an → Meldung bleibt eine Weile als Hinweis, Lernen läuft weiter
        hass.states.async_set("climate.bad", "heat", {"min_temp": 4, "max_temp": 35})
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert coord.zones["bad"].valve_frac is not None
        assert any("wieder eingeschaltet" in p for p in hass.states.get("binary_sensor.bad_problem_lh").attributes["probleme"])
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_temperature_change_works_with_preset_and_presence(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    cid = _eid(hass, entry, "climate", "bad_climate")
    await hass.services.async_call("climate", "set_preset_mode", {"entity_id": cid, "preset_mode": "eco"}, blocking=True)
    await hass.services.async_call("climate", "set_temperature", {"entity_id": cid, "temperature": 24.0}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 24.0  # vorher: blieb auf Eco (21,5)
    # Anwesenheitswechsel beendet die Übersteuerung
    await hass.services.async_call(
        "select", "select_option", {"entity_id": _eid(hass, entry, "select", "presence"), "option": "abwesend"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 17.0
    # Handbetrieb: neue Temperatur gilt sofort
    await hass.services.async_call("climate", "set_temperature", {"entity_id": cid, "temperature": 22.0}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": _eid(hass, entry, "select", "presence"), "option": "zuhause"}, blocking=True
    )
    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": cid, "hvac_mode": "heat"}, blocking=True)
    await hass.services.async_call("climate", "set_temperature", {"entity_id": cid, "temperature": 20.5}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 20.5
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_vacation_with_and_without_return(hass: HomeAssistant, freezer) -> None:
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    coord = entry.runtime_data
    cid = _eid(hass, entry, "climate", "bad_climate")
    presence = _eid(hass, entry, "select", "presence")
    ret_eid = _eid(hass, entry, "datetime", "return_at")

    async def choose(option: str) -> None:
        await hass.services.async_call("select", "select_option", {"entity_id": presence, "option": option}, blocking=True)
        await hass.async_block_till_done()

    # alte Rückkehrzeit vom letzten Urlaub steht noch drin → darf nicht sofort auf „Zuhause“ springen
    coord.return_at = dt_util.utcnow() - timedelta(days=10)
    await choose("urlaub")
    assert coord.presence == "urlaub" and coord.return_at is None
    assert hass.states.get(cid).attributes["temperature"] == 17.0  # Urlaub ohne Rückkehr: abgesenkt
    # Rückkehr in 2 Tagen eintragen: bis dahin abgesenkt, der Plan sieht den Komfort danach
    back = dt_util.utcnow() + timedelta(days=2)
    await hass.services.async_call("datetime", "set_value", {"entity_id": ret_eid, "datetime": back}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(cid).attributes["temperature"] == 17.0
    assert coord.target_at(coord.zones["bad"], back.timestamp() + 60).setpoint == 23.5
    # eine Stunde nach der Rückkehr automatisch wieder „Zuhause“
    freezer.move_to(back + timedelta(hours=1, minutes=5))
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.presence == "zuhause"
    assert hass.states.get(cid).attributes["temperature"] == 23.5
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_heating_limit_has_hysteresis(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    coord = entry.runtime_data
    for mean, winter in ((16.3, True), (16.6, False), (16.0, False), (15.6, False), (15.4, True), (16.4, True)):
        coord.t_out_mean24 = mean
        with patch.object(coord.fusion, "update", return_value=None):  # kein Außenwert → Mittel bleibt stehen
            await coord.async_refresh()
        assert coord.heating_season is winter, mean
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_stale_room_sensor_counts_as_missing(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set("sensor.raum", "21.0")
    assert _num(hass, "sensor.raum", SENSOR_STALE_S) == 21.0
    freezer.tick(timedelta(seconds=SENSOR_STALE_S + 60))  # Batterie leer: keine Meldung mehr
    assert _num(hass, "sensor.raum", SENSOR_STALE_S) is None
    assert _num(hass, "sensor.raum") == 21.0  # ohne Altersgrenze (z. B. Außenfühler) weiter nutzbar


async def test_season_switch_closes_valves_and_pauses_learning(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "number", "set_value")
    with patch.object(trv_mod, "BUMP_DELAY_S", 0):
        entry = await _setup(hass)
        coord = entry.runtime_data
        async_mock_service(hass, "climate", "set_hvac_mode")
        # TRV steht schon auf externem Fühler → kein Aufruf des (hier echten) select-Dienstes nötig
        hass.states.async_set("select.bad_temperature_sensor_select", "external", {"options": ["internal", "external"]})
        await hass.services.async_call("switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "bad_active")}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get(_eid(hass, entry, "binary_sensor", "heating_season")).state == "on"

        # Sommer: Ventil zu, Lernen pausiert
        calls.clear()
        await hass.services.async_call(
            "select", "select_option", {"entity_id": _eid(hass, entry, "select", "season"), "option": "sommer"}, blocking=True
        )
        await hass.async_block_till_done()
        last = {c.data["entity_id"]: c.data["value"] for c in calls}
        assert last["number.bad_valve_opening_degree"] == 0
        assert hass.states.get(_eid(hass, entry, "sensor", "bad_status")).state == "sommer"
        assert hass.states.get(_eid(hass, entry, "binary_sensor", "heating_season")).state == "off"
        z = coord.zones["bad"]
        assert z.learner.blocked_until > 0
        n = z.learner.samples
        for _ in range(5):
            coord._last_ts = None
            await coord.async_refresh()
        assert z.learner.samples == n

        # Winter erzwingt Heizen, auch wenn es draußen warm ist
        coord.t_out_mean24 = 25.0
        await hass.services.async_call(
            "select", "select_option", {"entity_id": _eid(hass, entry, "select", "season"), "option": "winter"}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(_eid(hass, entry, "sensor", "bad_status")).state != "sommer"
        assert coord.heating_season
        # Automatisch: Heizgrenze (16 °C) entscheidet → bei 25 °C Sommer
        await hass.services.async_call(
            "select", "select_option", {"entity_id": _eid(hass, entry, "select", "season"), "option": "auto"}, blocking=True
        )
        await hass.async_block_till_done()
        assert not coord.heating_season
        assert coord._export()["season"] == "auto"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_explanation_problems_and_diagnostics(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    coord = entry.runtime_data
    expl = hass.states.get("sensor.bad_erklaerung_lh")
    assert expl is not None and expl.state.startswith("Nur beobachten")
    assert len(expl.attributes["plan"]) == 48 and {"zeit", "soll", "prognose", "ventil"} <= set(expl.attributes["plan"][0])
    assert expl.attributes["lernt"] is True
    assert hass.states.get("binary_sensor.bad_problem_lh").state == "off"

    # Thermostat weg → Problem, Lernen pausiert (Ventilstellung unbekannt)
    hass.states.async_set("climate.bad", "unavailable")
    await coord.async_refresh()
    await hass.async_block_till_done()
    prob = hass.states.get("binary_sensor.bad_problem_lh")
    assert prob.state == "on" and "nicht erreichbar" in prob.attributes["probleme"][0]
    assert hass.states.get("sensor.bad_erklaerung_lh").attributes["lernt"] is False

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["zonen"]["bad"]["probleme"] and "modell" in diag["zonen"]["bad"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_supply_sensor_learns_in_observe_mode(hass: HomeAssistant, freezer) -> None:
    """Rohrfühler zählt auch, wenn die Zone nur beobachtet (Ventil vom TRV selbst geöffnet)."""
    async_mock_service(hass, "number", "set_value")
    _trv(hass, "bad")
    hass.states.async_set("climate.bad", "heat", {"hvac_action": "heating", "min_temp": 4, "max_temp": 35})
    hass.states.async_set("number.bad_valve_opening_degree", "80")
    hass.states.async_set("sensor.bad_temp", "20.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("binary_sensor.fenster_bad", "off")
    hass.states.async_set("sensor.rohr", "45.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    hass.states.async_set("sensor.aussen", "2.0", {"unit_of_measurement": "°C", "device_class": "temperature"})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN,
                            data={CONF_ZONES: [ZONE], CONF_SUPPLY: "sensor.rohr", CONF_SUPPLY_ZONE: "bad",
                                  CONF_OUTDOOR: "sensor.aussen"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    for _ in range(8):  # 40 min
        freezer.tick(timedelta(minutes=5))
        for eid, val in (("sensor.rohr", "45.0"), ("sensor.bad_temp", "20.0")):
            hass.states.async_set(eid, val, {"unit_of_measurement": "°C", "device_class": "temperature"}, force_update=True)
        await coord.async_refresh()
        await hass.async_block_till_done()
    assert coord.supply.n > 0
    sup = hass.states.get("sensor.vorlauf_lh")
    assert sup.attributes["quelle"] == "gemessen" and float(sup.state) == 47.0  # Rohr + 2 K
    assert sup.attributes["rohrfuehler"] == 45.0 and sup.attributes["rohrfuehler_status"].startswith("zählt –")
    assert "gemessen" in hass.states.get("sensor.bad_erklaerung_lh").attributes["vorlauf_quelle"]
    # Kopf aus → Ventil zu → Rohrwert wird angezeigt, zählt aber nicht (mit Grund)
    hass.states.async_set("climate.bad", "off", {"min_temp": 4, "max_temp": 35})
    for _ in range(4):
        freezer.tick(timedelta(minutes=5))
        for eid, val in (("sensor.rohr", "30.0"), ("sensor.bad_temp", "20.0")):
            hass.states.async_set(eid, val, {"unit_of_measurement": "°C", "device_class": "temperature"}, force_update=True)
        await coord.async_refresh()
        await hass.async_block_till_done()
    sup = hass.states.get("sensor.vorlauf_lh")
    assert sup.attributes["quelle"] == "Heizkurve" and sup.attributes["rohrfuehler"] == 30.0
    assert sup.attributes["rohrfuehler_status"] == "zählt nicht – Ventil Bad zu"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_model_uses_measured_supply_once_curve_learned(hass: HomeAssistant, freezer) -> None:
    """Die Startwerte der Heizwirkung passen zur angenommenen Heizkurve. Vor dem Lernen der Kurve ließe ein
    Messwert (z. B. 31 statt 37 °C) die Heizkörper viel zu schwach erscheinen – das Modell nimmt den
    gemessenen Vorlauf deshalb erst, wenn die Kurve gelernt (und die Heizwirkung umgerechnet) ist."""
    async_mock_service(hass, "number", "set_value")
    _trv(hass, "bad")
    hass.states.async_set("climate.bad", "heat", {"hvac_action": "heating", "min_temp": 4, "max_temp": 35})
    hass.states.async_set("number.bad_valve_opening_degree", "80")
    hass.states.async_set("binary_sensor.fenster_bad", "off")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN,
                            data={CONF_ZONES: [ZONE], CONF_SUPPLY: "sensor.rohr", CONF_SUPPLY_ZONE: "bad",
                                  CONF_OUTDOOR: "sensor.aussen"})

    def feed() -> None:
        for eid, val in (("sensor.rohr", "29.0"), ("sensor.bad_temp", "20.0"), ("sensor.aussen", "13.0")):
            hass.states.async_set(eid, val, {"unit_of_measurement": "°C", "device_class": "temperature"}, force_update=True)

    feed()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = entry.runtime_data
    for _ in range(10):
        freezer.tick(timedelta(minutes=5))
        feed()
        await coord.async_refresh()
    assert 0 < coord.supply.n < 30
    assert coord.supply.measured(dt_util.utcnow().timestamp()) == 31.0
    assert coord.t_supply == coord.curve.supply(13.0, dt_util.now().hour)  # Modell: noch Heizkurve
    sup = hass.states.get("sensor.vorlauf_lh")
    assert float(sup.state) == 31.0 and "/30" in sup.attributes["rohrfuehler_status"]  # Anzeige: Messwert
    for _ in range(30):
        freezer.tick(timedelta(minutes=5))
        feed()
        await coord.async_refresh()
    assert coord.supply.curve_params() is not None and coord.t_supply == 31.0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reset_learning_button(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")
    entry = await _setup(hass)
    coord = entry.runtime_data
    z = coord.zones["bad"]
    z.learner.samples = 500
    z.controller.d = 0.4
    coord.fusion.bias[3] = 1.5  # Sensorabgleich bleibt
    press = {"entity_id": "button.lernen_zuruecksetzen_lh"}
    # erster Druck: nur Warnung, nichts passiert
    await hass.services.async_call("button", "press", press, blocking=True)
    await hass.async_block_till_done()
    assert coord.zones["bad"].learner.samples == 500
    assert hass.states.get("button.lernen_zuruecksetzen_lh").attributes["wartet_auf_bestaetigung"] is True
    # zweiter Druck innerhalb von 60 s: zurücksetzen
    await hass.services.async_call("button", "press", press, blocking=True)
    await hass.async_block_till_done()
    z = coord.zones["bad"]
    assert z.learner.samples == 0 and z.controller.d == 0.0 and z.learner.progress() == 0
    assert coord.fusion.bias[3] == 1.5
    assert coord._export()["zones"]["bad"]["learner"]["samples"] == 0
    # danach ist die Sicherung wieder scharf: ein einzelner Druck setzt nicht zurück
    z.learner.samples = 7
    await hass.services.async_call("button", "press", press, blocking=True)
    await hass.async_block_till_done()
    assert coord.zones["bad"].learner.samples == 7
    assert await hass.config_entries.async_unload(entry.entry_id)
