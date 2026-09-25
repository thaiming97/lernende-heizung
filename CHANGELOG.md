# Änderungen

Jede Version bekommt hier einen Abschnitt `## x.y.z – Datum`. Wird die Version in
`manifest.json` erhöht und nach `main` gepusht, legt GitHub automatisch ein Release mit
diesem Abschnitt als Beschreibung an (HACS zeigt ihn beim Update an).

## 0.4.0 – 2026-09-25

**Vorlauffühler (Rohrfühler am Heizkörper)**
- Zählt jetzt auch im Beobachtungsmodus – bisher nur, wenn die Zone aktiv geregelt wurde.
- Der gemessene Vorlauf fließt direkt ins Modell, solange am Fühler-Heizkörper Wasser fließt
  (Ventil offen und Rohr deutlich wärmer als der Raum).
- Erkennt eine **Nachtabsenkung des Kessels** (Vorlauf je Tagesstunde) und plant das Vorheizen
  entsprechend früher.
- Erkennt, wenn der **Kessel keine Wärme liefert** (Ventil offen, Rohr bleibt kalt).
- Sobald die Heizkurve gelernt ist, wird das bisher Gelernte umgerechnet statt verworfen
  (vorher hätte die Heizwirkung um bis zu 40 % danebengelegen).
- Sensor „Vorlauf“ zeigt, ob gemessen oder aus der Heizkurve, dazu die gelernte Heizkurve und
  eine erkannte Nachtabsenkung.

**Was denkt die Regelung?**
- Neuer Sensor **„Erklärung“** je Zone: ein Satz, was gerade passiert und warum – z. B.
  „Heizt vor: 22,5 °C ab 15:30, jetzt 20,4 °C, Ventil 80 %.“ oder „Ventil zu: Sonne bringt in
  3 h ca. +0,8 K.“ Im Beobachtungsmodus steht dort, was sie stellen *würde*.
- Dazu als Attribute: Soll/Ist, nächster Sollwertwechsel, Vorheizstart, erwartete Sonnenwärme,
  Zusatz- und Grundwärme, Modellfehler, Lernfortschritt, ob gerade gelernt wird (und wenn nicht,
  warum), Vorlauf – und der **12-Stunden-Plan** (Uhrzeit, Soll, Prognose, Ventil) für Diagramme.
- Neuer Sensor **„Problem“** je Zone mit Liste: Raumsensor oder Thermostat weg, Befehl kommt
  am Thermostat nicht an, Sicherheitsbetrieb, Kessel kalt.
- **Diagnose-Download** unter Geräte & Dienste → Lernende Heizung → ⋮ → Diagnose herunterladen.

**Robustheit**
- Ist kein Thermostat einer Zone erreichbar, pausiert das Lernen (vorher nahm es an, das Ventil
  stehe wie befohlen).
- Klima-Entity zeigt „heizt“ nach der tatsächlichen Ventilstellung, auch im Beobachtungsmodus.

## 0.3.0 – 2026-09-24

- Neue Auswahl **„Heizsaison“**: *Automatisch* (wie bisher: über der Heizgrenze, 24-h-Mittel
  außen, wird nicht geheizt), *Winter* (heizt immer, auch an warmen Tagen) oder *Sommer*
  (Heizung aus, Ventile zu, einmal pro Woche kurz durchbewegen).
- Im Sommer **pausiert das Lernen**. Offene Fenster, Sommerlüftung und starke Sonne passen nicht
  zum Heizbetrieb, und über Monate hätte die Regelung sonst vergessen, wie stark die Heizkörper
  heizen.
- Neuer Sensor **„Heizperiode“** (an = es wird geheizt und gelernt) – zeigt auch im
  Automatik-Betrieb, was gerade gilt.

## 0.2.0 – 2026-09-24

**Regelung**
- Die Grundwärme einer Zone (Personen, Geräte) wird jetzt mitgelernt. Vorher landete sie
  in der Störgröße und wurde 12 Stunden lang in die Zukunft fortgeschrieben.
- Kurzfristige Störungen (Kochen, Besuch) klingen im Plan nach etwa 2 Stunden ab und
  verzögern das Vorheizen nicht mehr.
- Bei offenem Fenster (und 30 Minuten danach) wird das Auskühlen nicht mehr als Störung
  gelernt – vorher heizte der Regler danach zu kräftig nach.

**Sicherheit**
- Sicherheitsbetrieb: Erklärt das gelernte Modell die Messung dauerhaft nicht, übernimmt ein
  einfacher PI-Regler (Status „Sicherheitsbetrieb“). Bisher war er vorhanden, aber nie aktiv.
- Ein Raumsensor, der sich 3 Stunden nicht meldet (z. B. leere Batterie), gilt als
  ausgefallen, statt mit dem letzten Wert weiterzuregeln.
- Hauptschalter bzw. „Aktiv regeln“ aus: Der Thermostatkopf regelt wieder mit seinem
  eingebauten Fühler. Vorher blieb er auf „extern“ und regelte auf einen eingefrorenen Wert.

**Sonstiges**
- Die Schätzung der Speichermasse übersteht Neustarts.
- Neuer Diagnosesensor „Grundwärme (Personen, Geräte)“; „Störwärme“ heißt jetzt
  „Störwärme kurzfristig (Kochen, Besuch)“.
- Bisher Gelerntes wird beim Update übernommen.

## 0.1.0 – 2026-09-23

Erste Version: vorausschauende Regelung (12 h), Online-Lernen je Zone, direkte Ventilsteuerung
für Sonoff TRVZB, Beobachtungsmodus, Einrichtung über die Oberfläche. Entity-IDs enden auf `_lh`.
