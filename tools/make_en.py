"""Erzeugt translations/en.json und strings.json aus der deutschen Fassung (gleiche Struktur)."""

import json
from pathlib import Path

base = Path(__file__).parents[1] / "custom_components" / "lernende_heizung"
de = json.loads((base / "translations" / "de.json").read_text(encoding="utf8"))
en = json.loads(json.dumps(de))

err = {
    "invalid_schedule": "Schedule not understood. Example: Mo-Fr 06:00-08:00, 16:30-22:00; Sa-So 07:30-22:30",
    "name_required": "Please enter a name.",
    "name_exists": "Zone already exists.",
    "trv_required": "Select at least one thermostat.",
}
en["config"]["abort"]["already_configured"] = "Already set up. Add more zones via Configure."
en["config"]["error"] = en["options"]["error"] = err
gen = {
    "weather_entity": "Weather service (temperature and forecast)",
    "outdoor_sensor": "Own outdoor sensor (optional, offset is learned)",
    "sun_sensor": "Outdoor illuminance sensor (optional)",
    "heating_limit": "Heating limit (24 h outdoor mean)",
}
en["config"]["step"]["user"] = {"title": "Learning heating – home", "description": "Suggestions are pre-filled. Everything can be changed later.", "data": gen}
zd = {
    "name": "Name", "temp_sensor": "Room temperature sensor", "temp_sensor_2": "Second sensor (optional)",
    "trvs": "Thermostatic heads", "windows": "Window/door contacts (optional)", "comfort_temp": "Comfort temperature",
    "eco_delta": "Setback", "away_temp": "Away/vacation temperature", "schedule": "Comfort times",
    "radiator_kw": "Radiator nominal power (initial value)", "area_m2": "Zone area (initial value)",
}
en["config"]["step"]["zone"] = {
    "title": "Zone", "description": "A zone = rooms controlled together; its radiators open equally.", "data": zd,
    "data_description": {
        "schedule": "e.g. Mo-Fr 06:00-08:00, 16:30-22:00; Sa-So 07:30-22:30 or immer",
        "radiator_kw": "A rough value is fine; the model learns the real one.",
        "temp_sensor_2": "Replaces the main sensor while it gets direct sun.",
    },
}
en["config"]["step"]["more"] = {"title": "Another zone?", "menu_options": {"zone": "Add another zone", "finish": "Finish"}}
o = en["options"]["step"]
o["init"] = {"title": "Settings", "menu_options": {"general": "Home (weather, outdoor, sun)", "supply": "Supply temperature sensor",
                                                  "add_zone": "Add zone", "edit_zone": "Edit zone", "remove_zone": "Remove zone"}}
o["general"] = {"title": "Home", "data": gen}
o["supply"] = {"title": "Supply sensor (optional)", "description": "Pipe sensor on a supply pipe (at a radiator or at the start of a branch); only valid while water flows – choose the zone whose valve sends water through this pipe.",
               "data": {"supply_sensor": "Pipe sensor", "supply_zone": "Water flows when this zone heats"}}
o["add_zone"] = {"title": "Add zone", "data": zd}
o["zone_form"] = {"title": "Edit zone", "data": zd}
o["edit_zone"] = {"title": "Edit zone", "data": {"zone": "Zone"}}
o["remove_zone"] = {"title": "Remove zone", "data": {"zone": "Zone"}}
names = {
    "master": "Control", "active": "Actively control", "presence": "Presence", "return_at": "Return from vacation",
    "window": "Window open", "preheat": "Preheating", "outdoor": "Outdoor temperature", "supply": "Supply temperature",
    "sun": "Solar irradiance", "valve": "Valve", "power": "Heating power", "energy": "Heating energy", "demand": "Heat demand",
    "forecast_1h": "Temperature in 1 h", "forecast_3h": "Temperature in 3 h", "preheat_start": "Next preheat start",
    "status": "Status", "saving": "Saving from setback", "learning": "Learning progress", "model_error": "Model error",
    "time_constant": "Thermal mass time constant", "heat_gain": "Heating effect at full opening", "heat_loss": "Heat loss",
    "disturbance": "Short-term gains (cooking, visitors)",
    "base_gain": "Base internal gains",
    "season": "Heating season", "heating_season": "Heating period", "explain": "Explanation", "problem": "Problem", "reset_learning": "Reset learned model",
}
for ents in en["entity"].values():
    for k, v in ents.items():
        if k in names:
            v["name"] = names[k]
en["entity"]["select"]["presence"]["state"] = {"zuhause": "Home", "abwesend": "Away", "urlaub": "Vacation"}
en["entity"]["select"]["season"]["state"] = {"auto": "Automatic (heating limit)", "winter": "Winter (heat)", "sommer": "Summer (off)"}
en["entity"]["climate"]["zone"]["state_attributes"]["preset_mode"]["state"] = {"none": "Schedule", "comfort": "Comfort", "eco": "Setback", "away": "Away"}
en["entity"]["sensor"]["status"]["state"] = {
    "komfort": "Comfort", "absenkung": "Setback", "vorheizen": "Preheating", "fenster": "Window open", "frostschutz": "Frost protection",
    "aus": "Off", "rueckfall": "Safe mode", "kein_sensor": "Sensor missing", "sommer": "Summer", "beobachten": "Observe only",
}
txt = json.dumps(en, ensure_ascii=False, indent=2) + "\n"
(base / "translations" / "en.json").write_text(txt, encoding="utf8")
(base / "strings.json").write_text(txt, encoding="utf8")
print("ok")
