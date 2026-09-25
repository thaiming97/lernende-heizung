"""Diagnose-Download (Geräte & Dienste → Lernende Heizung → ⋮ → Diagnose herunterladen):
alles, was die Regelung gelernt hat und gerade denkt – zum Nachvollziehen und für Fehlersuche."""

from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from homeassistant.core import HomeAssistant

from . import HeatingConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: HeatingConfigEntry) -> dict[str, Any]:
    c = entry.runtime_data
    now = time.time()
    zones = {}
    for zid, z in c.zones.items():
        d = z.decision
        zones[zid] = {
            "name": z.name,
            "config": z.cfg,
            "erklaerung": z.explanation,
            "info": z.info,
            "probleme": z.problems,
            "temperatur": z.temp,
            "ventil_stellung": z.valve_frac,
            "aktiv": z.controlling,
            "entscheidung": None if d is None else {"grund": d.reason, "ventil": d.valve, "stoerung": d.disturbance},
            "modell": c.zones[zid].controller.params.to_dict(),
            "lernen": {
                "fortschritt": z.learner.progress(), "fehler_k_h": z.learner.rmse(), "stichproben": z.learner.samples,
                "mit_heizen": z.learner.heat_samples, "kurve": z.learner.curve_ref,
                "kandidaten": [
                    {"k_ma": k.k_ma, "ventil_exp": k.valve_exp, "score": k.score, "n": k.n} for k in z.learner.cands
                ],
            },
            "regler": z.controller.export(),
            "sensorfilter": {"versatz": z.filt.offset, "n": z.filt.n, "gestoert": z.filt.disturbed},
            "thermostate": [
                {"entity": t.climate_id, "typ": t.kind, "erreichbar": t.available(), "zuletzt_gestellt": t.last_pct,
                 "befehl_haengt": t.write_mismatch(now), "zusatz_entities": t.entities}
                for t in z.trvs
            ],
        }
    return {
        "version": entry.version,
        "optionen": {k: v for k, v in c.opts.items() if k != "zones"},
        "regelung_an": c.master_on,
        "anwesenheit": c.presence,
        "heizsaison": c.season,
        "heizperiode": c.heating_season,
        "aussen": {"jetzt": c.t_out, "mittel_24h": c.t_out_mean24, "fusion": c.fusion.export()},
        "vorlauf": {
            "jetzt": c.t_supply, "gemessen": c.supply.measured(now), "kessel_kalt": c.supply.heat_missing(now),
            "kurve": asdict(c.curve), "lerner": c.supply.export(), "nachtabsenkung": c.supply.night_setback(),
        },
        "sonne": {"skala": c.sun.scale, "n": c.sun.n, "jetzt_fassaden": c.sun_now},
        "zonen": zones,
    }
