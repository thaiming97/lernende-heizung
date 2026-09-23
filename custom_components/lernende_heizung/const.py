"""Konstanten der Integration „Lernende Heizung"."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "lernende_heizung"
NAME: Final = "Lernende Heizung"
VERSION: Final = "0.1.0"

PLATFORMS: Final = ["binary_sensor", "climate", "datetime", "select", "sensor", "switch"]

# Allgemeine Optionen
CONF_WEATHER: Final = "weather_entity"
CONF_OUTDOOR: Final = "outdoor_sensor"
CONF_SUN: Final = "sun_sensor"
CONF_SUPPLY: Final = "supply_sensor"
CONF_SUPPLY_ZONE: Final = "supply_zone"
CONF_HEATING_LIMIT: Final = "heating_limit"
CONF_ZONES: Final = "zones"

# Zonen-Optionen
CONF_ZONE_ID: Final = "id"
CONF_ZONE_NAME: Final = "name"
CONF_TEMP: Final = "temp_sensor"
CONF_TEMP2: Final = "temp_sensor_2"
CONF_TRVS: Final = "trvs"
CONF_WINDOWS: Final = "windows"
CONF_COMFORT: Final = "comfort_temp"
CONF_ECO_DELTA: Final = "eco_delta"
CONF_AWAY: Final = "away_temp"
CONF_SCHEDULE: Final = "schedule"
CONF_RAD_KW: Final = "radiator_kw"
CONF_AREA: Final = "area_m2"

DEFAULT_HEATING_LIMIT: Final = 16.0
DEFAULT_COMFORT: Final = 21.0
DEFAULT_ECO_DELTA: Final = 2.0
DEFAULT_AWAY: Final = 17.0
DEFAULT_SCHEDULE: Final = "Mo-Fr 06:00-08:00, 16:30-22:00; Sa-So 07:30-22:30"
DEFAULT_RAD_KW: Final = 1.5
DEFAULT_AREA: Final = 15.0

# Laufzeit
CYCLE_S: Final = 300
REPLAN_S: Final = 900
WINDOW_LEARN_PAUSE_S: Final = 1800
SENSOR_STALE_S: Final = 1800
STORE_VERSION: Final = 1
STORE_SAVE_DELAY_S: Final = 600
PARAM_REFRESH_S: Final = 6 * 3600

# Anwesenheit
PRESENCE_HOME: Final = "zuhause"
PRESENCE_AWAY: Final = "abwesend"
PRESENCE_VACATION: Final = "urlaub"
PRESENCE_OPTIONS: Final = [PRESENCE_HOME, PRESENCE_AWAY, PRESENCE_VACATION]

# Zonen-Betriebsarten (Presets des climate-Entitys)
PRESET_SCHEDULE: Final = "none"
PRESET_COMFORT: Final = "comfort"
PRESET_ECO: Final = "eco"
PRESET_AWAY: Final = "away"
