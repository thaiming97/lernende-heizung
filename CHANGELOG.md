# Änderungen

Jede Version bekommt hier einen Abschnitt `## x.y.z – Datum`. Wird die Version in
`manifest.json` erhöht und nach `main` gepusht, legt GitHub automatisch ein Release mit
diesem Abschnitt als Beschreibung an (HACS zeigt ihn beim Update an).

## 0.5.3 – 2026-09-25

- Sensor „Vorlauf (geschätzt)“ heißt jetzt **„Vorlauf“**: Er zeigt den gemessenen Vorlauf, sobald
  Heizwasser am Fühler fließt, sonst den Wert aus der Heizkurve (Attribut „quelle“).
- Mit eingetragenem Vorlauffühler zeigt er zusätzlich den **aktuellen Rohrwert** (Attribut
  „rohrfuehler“) und **warum er gerade zählt oder nicht** („rohrfuehler_status“, z. B. „zählt nicht –
  Ventil Wohnen zu“).
- Einstellungen: Der Fühler darf auch am Anfang eines Heizstrangs sitzen; die Zonenauswahl heißt
  jetzt „Wasser fließt, wenn diese Zone heizt“.

## 0.5.2 – 2026-09-25

Fehlerkorrekturen aus einer Überprüfung der Regellogik:

- **Gelerntes wird jetzt auch im laufenden Betrieb gespeichert** (alle 15 Minuten). Bisher
  landete es nur beim sauberen Beenden von Home Assistant auf der Platte – nach einem Absturz
  oder Stromausfall war alles seit dem letzten Neustart verloren.
- **Nach dem Lüften kein Vollgas mehr**: Der Filter gegen Sonne auf dem Raumsensor hielt nach
  dem Fensterschließen den kalten Wert bis zu einer Stunde fest (die Luft wird dann ganz echt
  schnell wieder warm) – in Räumen ohne Zweitsensor heizte die Regelung so lange voll. Er greift
  jetzt nur noch, wenn Sonne scheinen kann, und nicht in der Stunde nach dem Lüften.
- **Ausgeschaltete Thermostatköpfe werden bemerkt**: Wird ein Kopf während der Regelung auf
  „Aus“ gestellt (von Hand, Automation, nach Batteriewechsel) oder war er beim Übernehmen nicht
  erreichbar, stellt die Regelung ihn wieder auf Heizen und meldet es unter „Problem“. Kam ein
  Ventilbefehl nicht an, wird er wiederholt. Solange die Ventilstellung unsicher ist, pausiert
  das Lernen (sonst hielte das Modell den Heizkörper für schwächer, als er ist).
- **Vorlauffühler** zählt schon ab 8 % Ventilöffnung (bisher 30 % – in gut gedämmten Wohnungen
  steht das Ventil fast nie so weit offen). „Kessel liefert keine Wärme“ weiterhin nur bei weit
  offenem Ventil, damit es keine Fehlalarme gibt.
- **Temperatur verstellen wirkt immer**: Bei aktivem Preset (Komfort/Eco/Abwesend) oder
  Anwesenheit „Abwesend“ wurde eine neue Temperatur bisher ignoriert. Sie gilt jetzt bis zum
  nächsten Wechsel im Zeitplan; ein Wechsel der Anwesenheit hebt sie auf.
- **Heizgrenze mit Schaltabstand** (±0,5 K), damit die Automatik um 16 °C herum nicht zwischen
  Sommer und Winter hin- und herschaltet.
- Zeitplan versteht englische Tage vollständig (bisher scheiterten Tue, Wed, Thu, Sun).

## 0.5.1 – 2026-09-25

- „Gelerntes zurücksetzen“ mit Sicherung: Der erste Druck zeigt eine Warnung (unter
  Benachrichtigungen), was verloren geht. Erst ein zweiter Druck innerhalb von 60 Sekunden setzt
  wirklich zurück.

## 0.5.0 – 2026-09-25

- Neuer Knopf **„Gelerntes zurücksetzen“**: verwirft das gelernte Wärmeverhalten aller Zonen und
  beginnt bei den Startwerten neu – z. B. zum Start der Heizperiode, wenn bisher nur ohne Heizung
  gelernt wurde. Der Abgleich der Sensoren und die Heizkurve aus dem Vorlauffühler bleiben.

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
