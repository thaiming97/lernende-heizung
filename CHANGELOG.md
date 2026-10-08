# Änderungen

Jede Version bekommt hier einen Abschnitt `## x.y.z – Datum`. Wird die Version in
`manifest.json` erhöht und nach `main` gepusht, legt GitHub automatisch ein Release mit
diesem Abschnitt als Beschreibung an (HACS zeigt ihn beim Update an).

## 0.6.0 – 2026-10-08

- **Neu: Sofi-Modus.** Schalter „Sofi da“ (`switch.sofi_lh`). Je Zone lässt sich unter
  „Konfigurieren“ → „Zone bearbeiten“ eine *Temperatur, wenn Sofi da ist* eintragen (leer = Raum bleibt
  wie immer). Ist der Schalter an, gilt sie statt der Komforttemperatur (Absenkung/Eco im gleichen Abstand
  darunter) – auch wenn die Anwesenheit auf „Abwesend“ oder „Urlaub“ steht, denn Sofi ist ja da. Schalter
  aus → wieder die normalen Temperaturen. Eine von Hand mit +/− verstellte Temperatur dieser Räume endet
  beim Umschalten; eine feste Temperatur („Heizen“) bleibt. Die Erklärung beginnt dann mit „Sofi da –“.

## 0.5.7 – 2026-10-08

- **Lernen läuft nicht mehr weg.** Keine gelernte Kennzahl darf negativ werden. Bisher wurde ein Wert, der
  unter 0 wollte, einfach auf 0 gesetzt – der Lerner glich das dann über eine andere, zusammenhängende
  Kennzahl aus, die immer weiter weglief. In der simulierten Saison landete so die Mitheizung durch die
  Nachbarräume im Schlafzimmer am Anschlag (40× zu hoch), der Vorhersagefehler verdreifachte sich bis an
  die Grenze, ab der die Regelung in den einfachen Notbetrieb wechselt. Jetzt werden zusammenhängende
  Werte gemeinsam nachgeführt: Der Vorhersagefehler bleibt in allen Räumen so klein, wie es das
  Messrauschen zulässt, und die gelernten Werte liegen näher an der Wirklichkeit (Bad: Heizwirkung 2,1–2,5
  statt 4,5, wahr 2,2). Geregelt wird in der Simulation gleich gut, mit etwas weniger Ventilbefehlen.

## 0.5.6 – 2026-10-08

Fehlerkorrekturen aus einer gründlichen Gesamtprüfung:

- **Vorlauffühler – falsche „Absenkung“**: In der ersten Stunde mit Messwerten wurde die Abweichung von
  der angenommenen Heizkurve als Absenkung genau dieser Uhrzeit gelernt (z. B. „17 Uhr: −6 K“). Der
  Stundenversatz wird jetzt erst gelernt, wenn das Niveau gemessen ist. Bisher Gelerntes dazu wird beim
  Update einmal verworfen und neu gelernt (die Heizkurve selbst bleibt).
- **Vorlauffühler – Übergang**: Das Modell rechnet erst mit dem gemessenen Vorlauf, wenn die Heizkurve
  gelernt ist (30 Messungen). Vorher hätte ein einzelner Messwert die Heizkörper viel zu schwach
  erscheinen lassen. Der Sensor „Vorlauf“ zeigt trotzdem gleich den Messwert, der Status den
  Fortschritt („Heizkurve wird gelernt: 12/30 Messungen“).
- Ohne Raumtemperatur zählt der Vorlauffühler nicht (es lässt sich nicht sagen, ob Wasser fließt).
- **Temperatur mit +/− bei Zeitplan „immer“** bleibt jetzt bestehen – bisher sprang sie nach 4 Stunden
  stillschweigend zurück. Sie gilt (auch über einen Neustart) bis zum nächsten Wechsel im Zeitplan bzw.
  bis Preset, Modus oder Anwesenheit geändert werden.
- **Komfort/Eco/Weg im Modus „Heizen“** hatte keine Wirkung. Die Auswahl schaltet jetzt auf Automatik.
- Lernen: Während einer Lernpause (Fenster, Sommer, kaltes Rohr) laufen Speichermasse und Heizkörper im
  Modell mit der gemessenen Raumtemperatur weiter – vorher mit dem letzten Wert vor der Pause.

## 0.5.5 – 2026-10-08

Erfahrungen aus dem ersten Heiztag:

- **Kurz rausgehen schließt kein Ventil mehr**: Fenster und Türen zählen erst, wenn sie länger als
  1 Minute offen stehen. Bis dahin läuft alles normal weiter (auch das Lernen).
- **Nach dem Lüften 15 Minuten warten**: Ist das Fenster wieder zu, bleibt das Ventil noch
  15 Minuten geschlossen – die Luft wärmt sich zuerst aus Wänden und Möbeln wieder auf, sofort
  heizen würde überheizen. Danach regelt es sofort weiter. Die Erklärung zeigt, bis wann gewartet wird.
- **Neuere Zigbee2MQTT-Versionen**: Die Fühlerwahl am Thermostat heißt dort
  `local_temperature`/`remote_temperature` statt `internal`/`external`. Bisher wurde sie deshalb nicht
  umgestellt – vor allem beim Ausschalten der Regelung regelte der Kopf danach auf einen eingefrorenen
  Wert. Beide Namensvarianten funktionieren jetzt.
- Die Raumtemperatur geht mindestens alle 30 Minuten an die Thermostate, auch wenn sie sich nicht
  ändert (sonst hält der Kopf den externen Fühler womöglich für ausgefallen).
- **Vorlauffühler**: „Kessel liefert keine Wärme“ erst, wenn der Fühler schon einmal echten Vorlauf
  gemessen hat – liegt er noch nicht am Rohr, steht dort ein Hinweis statt eines Fehlalarms.
  Bleibt das Rohr bei offenem Ventil kalt, pausiert das Lernen (sonst hielte das Modell die
  Heizkörper für schwächer, als sie sind).
- „Lernen pausiert“ nennt jetzt den echten Grund (vorher stand nach dem Umschalten auf Winter
  fälschlich „Fenster war gerade offen“), und die Erklärung zeigt die gerade gestellte
  Ventilöffnung statt der vom letzten Takt.

## 0.5.4 – 2026-09-27

- **Urlaub** ohne eingetragene Rückkehrzeit senkt jetzt ab (bisher wurde normal weitergeheizt).
- Steht noch die Rückkehrzeit vom letzten Urlaub drin, springt „Urlaub“ nicht mehr sofort auf
  „Zuhause“ zurück – die alte Zeit wird gelöscht.

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
