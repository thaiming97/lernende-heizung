# Änderungen

Jede Version bekommt hier einen Abschnitt `## x.y.z – Datum`. Wird die Version in
`manifest.json` erhöht und nach `main` gepusht, legt GitHub automatisch ein Release mit
diesem Abschnitt als Beschreibung an (HACS zeigt ihn beim Update an).

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
