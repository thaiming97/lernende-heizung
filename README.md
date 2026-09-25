# Lernende Heizung

Vorausschauende, selbstlernende Heizkörperregelung für Home Assistant – als Ersatz für
Better Thermostat. Entwickelt für Sonoff TRVZB (Zigbee2MQTT oder ZHA), funktioniert grob
auch mit anderen Thermostatköpfen.

## Was sie macht

- **Lernt jede Zone**: Raumluft + Speichermasse der Wände, Einfluss von Nachbarräumen, Außen,
  Sonne (Ost/Süd/West getrennt) und wie stark der Heizkörper je Ventil-% heizt – laufend,
  auch während Better Thermostat noch regelt (Beobachtungsmodus).
- **Plant 12 Stunden voraus**: heizt rechtzeitig vor, damit es zur Komfortzeit warm ist, hört
  vor einer Absenkung oder vor erwarteter Sonne früh genug auf.
- **Stellt das Ventil direkt** (TRVZB: Öffnungs-/Schließgrad), batterieschonend gefiltert.
- **Sicherheit**: Fenster offen → Ventil zu; Frostschutz; Raumsensor fehlt oder meldet sich
  3 h nicht → feste mittlere Öffnung; passt das gelernte Modell nicht zur Messung → einfacher
  PI-Regler (Status „Sicherheitsbetrieb“); Hauptschalter aus → Thermostatköpfe regeln wieder
  selbst, mit ihrem eingebauten Fühler.
- **Erklärt sich selbst**: Sensor „Erklärung“ je Zone sagt in einem Satz, was die Regelung tut
  und warum; als Attribute der 12-h-Plan und alle Kennzahlen. Sensor „Problem“ meldet Störungen.
- **Vorlauffühler (optional)**: Rohrfühler am Vorlauf eines Heizkörpers – lernt die Heizkurve,
  eine Nachtabsenkung des Kessels und erkennt, wenn der Kessel nichts liefert.
- **Statistiken**: Heizleistung, Heizenergie, Wärmebedarf, Vorhersage 1 h/3 h, nächster
  Vorheizstart, Einsparung durch Absenkung, Lernfortschritt, Modellfehler, Zeitkonstante,
  Grundwärme (Personen, Geräte), geschätzter Vorlauf, Außentemperatur (Wetterdienst + eigener Fühler fusioniert).

In der Simulation mit echten Wetter- und Raumdaten (Winter 2025/26) hielt der Regler die
Komforttemperatur auf ±0,1 K, heizte pünktlich vor und schwang kaum über – Better
Thermostat MPC v2 (Standardwerte) lag bei ±0,5–0,7 K.

## Installation (HACS)

1. HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories → dieses Repository, Typ
   „Integration“.
2. „Lernende Heizung“ installieren, Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Lernende Heizung“.
   Wetterdienst, Außenfühler und Sonnensensor werden vorgeschlagen; danach Zonen anlegen.

Kein YAML, keine Helfer. Alles Weitere über „Konfigurieren“.

Was sich in welcher Version geändert hat: [CHANGELOG.md](CHANGELOG.md) bzw. die
Releases auf GitHub (HACS zeigt die Notizen beim Update an).

## Zeitplan

Komfortzeiten als Text, z. B. `Mo-Fr 05:00-05:30, 15:30-22:30; Sa-So 08:00-22:30`
oder `immer`. Außerhalb gilt die Absenkung.

## Sommer / Winter

Auswahl „Heizsaison“: *Automatisch* entscheidet über die Heizgrenze (einstellbar unter
„Konfigurieren“ → Wohnung), *Winter* heizt immer, *Sommer* schaltet ab. Außerhalb der
Heizperiode sind die Ventile zu und das Lernen pausiert; der Sensor „Heizperiode“ zeigt, was gilt.

## Umstieg von Better Thermostat

Neue Zonen starten im **Beobachtungsmodus** (Schalter „Aktiv regeln“ aus): sie lernen mit,
schreiben aber nichts. Wie stark der Heizkörper heizt, lernen sie dabei nur, wenn ein anderer
Regler (z. B. Better Thermostat) die Ventile tatsächlich bewegt – sonst erst im aktiven Betrieb.
Zum Umschalten je Zone: Better Thermostat für diese Zone deaktivieren,
dann „Aktiv regeln“ einschalten. Beide gleichzeitig aktiv führt zu Konflikten.

## Entwicklung

- `custom_components/lernende_heizung/core/` – Regelkern ohne HA-Abhängigkeit
  (Modell, Lernen, MPC, Zeitplan, Signale).
- Tests: `pip install pytest-homeassistant-custom-component numpy && pytest`
  (unter Windows zusätzlich `PYTHONPATH=tools/winshim`, HA selbst läuft nur unter Linux).

Lizenz: AGPL-3.0 (enthält Ideen/Erfahrungen aus Better Thermostat, ebenfalls AGPL-3.0).
