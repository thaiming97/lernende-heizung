"""Lernende Heizung – vorausschauende, selbstlernende Heizkörperregelung für Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import HeatingCoordinator

type HeatingConfigEntry = ConfigEntry[HeatingCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    coordinator = HeatingCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeatingConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_shutdown()
    return ok


async def _async_reload(hass: HomeAssistant, entry: HeatingConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
