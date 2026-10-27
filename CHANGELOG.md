# Änderungen

Jede Version bekommt hier einen Abschnitt `## x.y.z – Datum`. Wird die Version in
`manifest.json` erhöht und nach `main` gepusht, legt GitHub automatisch ein Release mit
diesem Abschnitt als Beschreibung an (HACS zeigt ihn beim Update an).

## 0.11.1 – 2026-10-27

- **Urlaub: Vorheizen zielt gleich auf die Temperatur zur Rückkehr.** In 0.11.0 galt ab dem Vorheizstart der
  normale Zeitplan von jetzt. Fiel der Start in eine Eco-Zeit (nachts oder werktags tagsüber), hätte die Zone nur
  bis Eco geheizt und den Rest wieder auf den letzten Drücker geplant – genau das, was am 25.10. zu spät kam.
- **Rückkehr verschoben:** Lief das Vorheizen schon, bricht es jetzt ab, die Zone senkt wieder ab, und der Start
  wird für die neue Rückkehrzeit neu gerechnet. Bisher heizte sie bis zur neuen Rückkehr durch.
- Wird die Rückkehrzeit gelöscht, gilt wieder „bis auf Weiteres absenken“ statt der alten Entscheidung.

## 0.11.0 – 2026-10-26

- **Urlaub: Die Heizung prüft, ob sich das Absenken überhaupt lohnt.** Mit eingetragener Rückkehrzeit rechnet sie
  beide Wege mit dem gelernten Modell durch: warm halten oder absenken und rechtzeitig wieder aufheizen. Spart das
  Absenken weniger als 10 % der Wärme, bleibt es warm. Hintergrund ist der erste Urlaub am 23.–25.10.: Die
  gut gedämmte Wohnung kühlte übers Wochenende nur 2–3 K ab, gespart waren grob 1–2 kWh, und beim Heimkommen um
  18 Uhr waren die Räume noch 0,3–0,6 K zu kalt (das Wohnzimmer erst am Montagmorgen warm). Nachgerechnet lohnt
  sich das Absenken hier erst ab etwa 10 Tagen. Die Erklärung sagt, was gilt („Urlaub: Absenken lohnt sich nicht
  (spart nur ~6 %), bleibt warm“), die Anwesenheits-Auswahl zeigt die geschätzte Ersparnis.
- **Lohnt es sich, wird sicher vorgeheizt.** Die Heizung rechnet den spätesten Start aus, ab dem sie mit voller
  Leistung pünktlich zur Rückkehr warm bekommt – vorsichtig, mit nur zwei Dritteln der gelernten Heizwirkung (über
  Stunden heizen die Heizkörper schwächer, als das Modell aus kurzen Abschnitten lernt). Der Start wird stündlich
  mit der echten Raumtemperatur nachgerechnet; ab dann gilt der normale Zeitplan, der Status steht auf
  „Vorheizen“. Bisher plante der Regler das Vorheizen nur 12 Stunden voraus und auf den letzten Drücker.

## 0.10.1 – 2026-10-20

- **„Türen offen“ hält keine alte Zusatzwärme mehr fest.** Bisher fror der Schalter die geschätzte Zusatzwärme
  (Duschen, Kochen, Sonne …) auf ihrem letzten Wert ein. Live am 20.10. war das gerade die Duschwärme im Bad: Die
  Heizung rechnete stundenlang mit Wärme, die es nicht mehr gab, ließ das Ventil fast zu, und das Bad fiel von 23,3
  auf 22,7 °C. Jetzt passt sich die Zusatzwärme bei offenen Türen weiter an die Messung an – so merkt die Heizung,
  wenn ein Raum auskühlt (nachgerechnet mit diesem Morgen: Bad-Ventil 67–100 % statt 4–24 %). Gelernt wird bei
  offenen Türen weiterhin nichts.
- **Eingefrorene Zusatzwärme klingt ab.** Beim offenen Fenster und in der Stunde nach dem Türen-Schließen bleibt die
  Zusatzwärme weiter eingefroren, klingt aber wie im Plan über rund zwei Stunden ab, statt stehen zu bleiben.

## 0.10.0 – 2026-10-19

- **Heizwirkung gilt für jede Außentemperatur gleich, sobald der Vorlauf gemessen wird.** Bisher lernte die
  Heizung die Wirkung der Heizkörper getrennt für −10, 0 und +10 °C außen. Das war gedacht, solange der Vorlauf
  nur geschätzt ist. Mit Vorlauffühler steckt die Außentemperatur aber schon im gemessenen Vorlauf – und die drei
  Werte passten nur zu dem Wetter, das es gerade gab. Live (nur 4–15 °C außen) hielt das Modell die Heizkörper im
  Wohnzimmer bei 0 °C für halb so stark wie bei +10 °C, obwohl der Vorlauf dann wärmer ist. Beim ersten Frost hätte
  es deshalb zu weit aufgedreht. Jetzt gibt es einen Wert. Beim Update übernimmt er die Wirkung, die bei der
  aktuellen Außentemperatur gilt – die Vorhersage für heute bleibt gleich. Mit den echten Messdaten der letzten
  elf Tage nachgerechnet: gleich genaue Vorhersage, bei 0 °C passen die Werte jetzt zu den gemessenen
  Aufheizraten vom letzten Winter. Ohne Vorlauffühler ändert sich nichts.
- **Nachtabsenkung des Kessels zählt als Vorlauf.** Nachts liegt das Rohr oft nur gut 4 K über der Raumtemperatur
  (live 25–26 °C). Bisher galt das als „Rohr kalt“: Das Lernen pausierte ausgerechnet nachts, wenn die Ventile
  offen stehen (bis zu einem Drittel des Tages). Jetzt zählt das Rohr, wenn es zum gelernten Vorlauf dieser Uhrzeit
  passt. Ruhendes Wasser (Rohr ≈ Raum) zählt weiter nicht.
- **„Kessel liefert keine Wärme“ erst nach einer Stunde.** Zu Beginn der Nachtabsenkung bleibt das Rohr oft knapp
  eine Stunde fast kalt. Das Modell rechnet dann wie bisher sofort mit kaltem Vorlauf, in der Problemliste und auf
  dem Vorlauf-Sensor steht es aber erst, wenn es eine Stunde anhält. Davor zeigt der Rohrfühler-Status „Kessel
  liefert gerade kaum Wärme“.

## 0.9.1 – 2026-10-11

- **Raumsensor fällt aus: nach der Haltezeit die übliche Öffnung.** Nach einer Stunde ohne Raumwert stellt die
  Heizung jetzt die mittlere Ventilöffnung der letzten rund 24 Stunden ein (mit 20 % Reserve, nie ganz zu).
  In 0.9.0 war es der Dauer-Wärmebedarf aus dem gelernten Modell. Mit den echten Werten nachgerechnet hätte
  das Bad damit nur 2 % bekommen, obwohl es nachts ganz offen stand. Der Modellwert ist dafür zu unsicher.
  Ohne Verlauf (gerade erst eingerichtet) gilt wie früher die feste Notöffnung. Die Erklärung sagt, was gilt.
- Hinweis zum Sensor „Wärmebedarf“: Er rechnet seit 0.9.0 mit den Nachbarzonen, bleibt aber ein Modellwert.
  Fürs Bad liegt er weiter deutlich unter dem, was es tatsächlich braucht.

## 0.9.0 – 2026-10-11

- **Vorlauffühler zählt für den ganzen Heizstrang.** Unter „Konfigurieren → Vorlauffühler“ lassen sich jetzt
  mehrere Zonen wählen: alle, deren Ventile Wasser am Fühler vorbeischicken. Er zählt, sobald eines davon offen
  ist. Bisher nur bei einer Zone – nachts, wenn nur das Bad heizte, wurde der echte Vorlauf verworfen, und die
  Nachtabsenkung des Kessels war nur für einen Teil der Nacht bekannt. Bestehende Einstellungen gelten weiter.
- **Die gelernte Heizkurve bleibt stabil.** Messungen aus der Nachtabsenkung des Kessels zählen nur noch für
  den Versatz ihrer Uhrzeit, nicht mehr für die Kurve selbst. Sonst hätten die vielen neuen Nachtwerte die
  Kurve Tag für Tag nach unten gezogen (Simulation: knapp 1 K in 10 Tagen), und die gelernte Heizwirkung wäre
  jedes Mal umgerechnet worden. Die Nachtabsenkung wird gegen die übliche Stunde erkannt.
- **Raumsensor fällt aus: erst halten, dann nach Bedarf.** Bisher sprang das Ventil sofort auf einen festen
  Wert, auch bei einem kurzen Aussetzer (z. B. wenn eine Sensorbox neu aufgespielt wird). Jetzt bleibt es eine
  Stunde lang, wie es war; danach stellt die Heizung die Öffnung ein, mit der das gelernte Modell die
  Wunschtemperatur hält (mit etwas Reserve, nie ganz zu). Die Erklärung sagt, welcher Fall gerade gilt.
- **Hängender Helligkeitssensor wird erkannt.** Meldet der Lux-Sensor über eine Stunde nichts, rechnet die
  Heizung mit Sonnenstand und Bewölkungsvorhersage. Bisher galt der letzte Wert weiter (am 10.10. zeigte
  „Sonnenstrahlung“ deshalb bis 23 Uhr 50 W/m²).
- **Hinweis bei nicht erreichbarem Fenster-/Türkontakt.** Ist ein Kontakt über eine Stunde nicht erreichbar,
  steht das in der Problemliste der Zone. Er zählt dann als geschlossen – die Heizung läuft weiter.
- **Wärmebedarf mit Nachbarräumen.** Der Sensor „Wärmebedarf“ rechnet jetzt mit der Temperatur der anderen
  Zonen. Das Bad (23,5 °C) verliert seine Wärme vor allem an die kühleren Räume nebenan und zeigte vorher
  fast 0 W, während sein Ventil nachts ganz offen stand.
- **Verlauf im Diagnose-Download:** die letzten 288 Entscheidungen je Zone (etwa 24 Stunden) mit Grund,
  Temperaturen, Ventil, Vorlauf, Sonne und Problemen – für die Fehlersuche.
- Kleinigkeit: Die Nachtabsenkung beim Vorlauf zeigt „ca. −5 K“ statt „ca, -5 K“.

## 0.8.1 – 2026-10-10

- **Kein Notbetrieb mehr direkt nach dem Neustart.** Startet Home Assistant, melden sich die Raumsensoren erst nach
  und nach. Bisher stellte die Heizung in dieser Zeit alle Ventile sofort auf die Notöffnung (12 %), und weil
  zwischen zwei Ventilbefehlen mindestens 20 Minuten liegen, blieb z. B. das Bad so lange fast zu. Jetzt bleiben
  die Ventile in den ersten 10 Minuten nach dem Start, wie sie sind; fehlt der Sensor danach immer noch, gilt
  wie bisher die Notöffnung.

## 0.8.0 – 2026-10-10

- **Von Hand eingestellt gilt bis Mitternacht.** Wer die Temperatur einer Zone verstellt, auf „Heizen“
  schaltet oder ein Preset wählt, behält das bis 0 Uhr – danach läuft die Zone wieder in Automatik. Bisher
  blieb eine verstellte Temperatur bei Zeitplan „immer“ unbefristet stehen. Der Regler plant das Ende schon
  mit ein (heizt bei Bedarf rechtzeitig für den Automatik-Sollwert). „Aus“ bleibt aus. Bestehende
  Einstellungen von Hand enden nach dem Update an der nächsten Mitternacht.
- **Man sieht, dass gerade von Hand eingestellt ist:** Status „Von Hand (bis 0 Uhr)“, die Erklärung beginnt
  mit „Von Hand bis 0 Uhr – …“, und das Thermostat hat die Attribute `manuell` (ja/nein) und `manuell_bis`.
  (Das bisherige Attribut `uebersteuert_bis` entfällt.)
- **Zweitsensor ersetzt den Raumsensor nur noch bei Sonne.** Der zweite Sensor einer Zone ist nur dafür da,
  Sonnenspitzen am Hauptsensor zu überbrücken. Bisher sprang er aber auch ein, wenn er selbst deutlich kälter
  wurde als sonst – z. B. die Küche beim Kochen oder Lüften. Dann rechnete die Zone Wohnen mit der Küche
  (20,8 statt 22,4 °C im Wohnzimmer), heizte unnötig auf und zeigte auf den Dashboards die falsche
  Temperatur. Ohne Sonne gilt jetzt immer der Hauptsensor, und große Abweichungen verstellen den gelernten
  Abstand der beiden Sensoren nicht mehr. Der Hinweis im Zonenformular sagt jetzt deutlich: nur ein Sensor
  im selben Raum, kein Nebenraum.

## 0.7.0 – 2026-10-09

- **Neu: Schalter „Türen offen“** (`switch.tueren_offen_lh`). Für Tage, an denen die Innentüren offen stehen,
  z. B. für den Saugroboter. Dann heizen sich die Räume gegenseitig ganz anders als sonst (das warme Bad gibt
  Wärme an Flur und Schlafzimmer ab), und die Heizung würde das als normales Verhalten der Räume lernen.
  Solange der Schalter an ist, lernt keine Zone, und noch eine Stunde nach dem Ausschalten nicht (die Luft
  braucht eine Weile, bis die Räume wieder für sich sind). Geheizt wird ganz normal weiter. Der Schalter
  wird nur von Hand bedient; steht er länger als 12 Stunden an, erscheint ein Hinweis in der Problemliste.

## 0.6.1 – 2026-10-09

Zwei Fehler aus dem ersten Heiztag:

- **Modellfehler hing tagelang am ersten Messwert.** Der gleitende Fehler zählte die allererste Stichprobe
  voll und ließ sie erst über Tage abklingen. Beim Einschalten der Heizung ist genau die oft daneben
  (Bad: 0,75 K/h, obwohl die Vorhersagen danach gut passten). Ab 200 Stichproben (Samstag) hätte das
  Bad deshalb grundlos in den Notbetrieb (einfacher PI-Regler) gewechselt. Jetzt ist es ein echtes
  Mittel über die letzten Tage; der alte Wert wird nach dem Update in ein bis zwei Tagen abgelöst.
- **Heizkurve konnte falsch herum gelernt werden.** Am ersten Abend fiel die Außentemperatur von 13 auf
  5 °C, und ab 22 Uhr senkte der Kessel nachts ab. Daraus wurde „je kälter, desto kälter der Vorlauf“
  (bei −10 °C nur 25 °C). Jetzt darf die Kurve bei Kälte nicht fallen, und die Steigung bleibt beim
  Startwert, bis Messungen bei deutlich verschiedenen Außentemperaturen vorliegen. Nach dem Update wird
  die Kurve aus den bisherigen Messungen sofort neu berechnet (bei dir etwa 34 °C bei −10 °C, 32 °C bei
  0 °C, 30 °C bei +10 °C).

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
