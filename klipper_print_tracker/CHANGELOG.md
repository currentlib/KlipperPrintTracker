# Changelog

## 0.3.0

- Several printers: a `printers` list, one MQTT device per printer plus a shared one, a printer switcher in the UI. Single-printer options keep working as `printer1`.
- Rate prints and give a failure reason from the notification, with tags and notes on the print page.
- Spool check when a print starts, with an optional automatic pause.
- Maintenance reminders by print hours, filament, prints and days.
- Failure analysis page, and failure details on every stopped print.
- Calibration log with detection of OrcaSlicer tests.
- Projects with target parts and progress.
- Data size sensor, thumbnail retention, periodic `git gc`.
- Database and settings history migrate on the first start, a copy of the old database stays as `tracker.db.pre-v2`.

## 0.2.0

- The web UI follows the Home Assistant theme and looks like the rest of HA.
- Sortable prints list, filter chips, loading and empty states.
- Part names: case-insensitive, `.stl_2` style suffixes, original casing from the G-code. Existing records are fixed on the first start.
- Currency shows as a short symbol, for example `грн`.

## 0.1.0

- First version: print tracking, settings history, MQTT entities and web UI.
