"""Knopf „Gelerntes zurücksetzen“: Wärmemodell aller Zonen verwerfen und neu lernen.

Sicherung gegen Versehen: Der erste Druck zeigt nur eine Warnung (Benachrichtigung); erst ein
zweiter Druck innerhalb von 60 Sekunden setzt wirklich zurück.
"""

from __future__ import annotations

import time

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeatingConfigEntry
from .coordinator import HeatingCoordinator
from .entity import HubEntity

CONFIRM_S = 60
NOTIFICATION_ID = "lernende_heizung_reset"
TITLE = "Lernende Heizung: Gelerntes zurücksetzen"
WARNING = (
    "**Achtung:** Damit wird verworfen, was die Regelung über deine Räume gelernt hat – wie schnell sie "
    "auskühlen, wie stark die Heizkörper heizen, Sonne und Grundwärme. Sie beginnt wieder bei den "
    "Startwerten und braucht danach etwa zwei Wochen Heizbetrieb, bis sie wieder genau regelt.\n\n"
    "Erhalten bleiben der Abgleich der Sensoren und die Heizkurve aus dem Vorlauffühler.\n\n"
    f"**Zum Bestätigen den Knopf innerhalb von {CONFIRM_S} Sekunden noch einmal drücken.** "
    "Sonst passiert nichts."
)
DONE = "Das Gelernte aller Zonen wurde zurückgesetzt. Die Regelung lernt ab jetzt neu."


async def async_setup_entry(hass: HomeAssistant, entry: HeatingConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([ResetLearningButton(entry.runtime_data)])


class ResetLearningButton(HubEntity, ButtonEntity):
    _platform = "button"
    _attr_icon = "mdi:restart-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HeatingCoordinator) -> None:
        super().__init__(coordinator, "reset_learning")
        self._armed_until = 0.0

    @property
    def extra_state_attributes(self) -> dict:
        armed = time.time() < self._armed_until
        return {"wartet_auf_bestaetigung": armed, "hinweis": f"Zweimal drücken (innerhalb {CONFIRM_S} s) zum Zurücksetzen"}

    async def async_press(self) -> None:
        now = time.time()
        if now >= self._armed_until:
            self._armed_until = now + CONFIRM_S
            persistent_notification.async_create(self.hass, WARNING, title=TITLE, notification_id=NOTIFICATION_ID)
            self.async_write_ha_state()
            return
        self._armed_until = 0.0
        self.coordinator.reset_learning()
        persistent_notification.async_create(self.hass, DONE, title=TITLE, notification_id=NOTIFICATION_ID)
        await self.coordinator.async_refresh()
