# Klipper Print Tracker

Tracks every print on your Klipper printer and keeps a git history of the slicer settings used for it. The add-on talks to Moonraker directly: nothing is installed on the printer and the slicer needs no post-processing script.

## Install

1. Add this repository in **Settings > Apps > App store > Repositories**: `https://github.com/currentlib/KlipperPrintTracker`.
2. Install **Klipper Print Tracker**. Home Assistant builds the image on your device, so the first install takes a few minutes on a Raspberry Pi.
3. Add your printer to the `printers` option, or set `moonraker_url` for a single printer, and start the add-on.
4. Turn on **Show in sidebar**.

For part counts, enable **Exclude objects** in your slicer (OrcaSlicer: Others > Exclude objects).

The add-on starts empty and only records jobs that finish after its first start.

## Options

| Option | Description |
|---|---|
| `printers` | List of `id` (a-z and 0-9), `name`, `moonraker_url`, optional `energy_sensor` |
| `moonraker_url`, `printer_name`, `energy_sensor` | The older single-printer options, used as `printer1` while `printers` is empty. Moonraker is for example `http://192.168.1.50:7125`, Creality K1 series printers also work on port `4408`. The energy sensor must be a **total** counter in kWh, a daily one breaks on prints past midnight |
| `electricity_price` | Price per kWh |
| `default_filament_price` | Price per kg, used when Spoolman has no price |
| `currency` | Display only |
| `google_sheets_config_entry` | When set, a row is appended for every print |
| `google_sheets_worksheet` | The worksheet must already exist |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | Only needed without the Mosquitto app |
| `direct_url` | Address of the optional direct port, adds `direct_url` to entities and events |
| `auto_fetch_layouts` | Generate slicer metadata at runtime for OrcaSlicer versions that aren't bundled |
| `spool_margin_percent` | Spare filament the active spool should have on top of the print, default 5 |
| `spool_check_auto_pause` | Pause when the filament isn't enough or the material differs, off by default |
| `abrasive_patterns` | Regular expression for abrasive filament, matched against material and spool name |
| `thumbnail_retention_days` | Older thumbnails are removed, print records stay. 0 keeps them all |
| `calibration_stale_days` | Age of a calibration that gets a "worth repeating" hint, default 180 |
| `log_level` | Log detail |

## Several printers

Each printer has its own Moonraker connection, reconnecting independently, and its own git repository in `/data/git/<id>/`. Separate repositories keep one printer's history from mixing with the other's, and the existing repository simply moves to `/data/git/printer1/`.

When you move from the single-printer options to the `printers` list, **keep the id `printer1`** for the existing printer, because its prints are stored under that id. Don't change an id later. Job ids are only unique per printer, so links now look like `/job/printer1:000042`. Older links keep working.

## Entities

With the Mosquitto app and the MQTT integration, the add-on creates a shared device **Print Tracker** with totals, and one device **Print Tracker (printer name)** per printer. The table lists the shared entities. Printer devices have the same set as `sensor.print_tracker_<id>_...`. Entity IDs are fixed so the dashboard works without editing.

| Entity | State | Attributes |
|---|---|---|
| `sensor.print_tracker_total_prints` | count | completed, cancelled, failed and the other totals |
| `sensor.print_tracker_success_rate` | % | |
| `sensor.print_tracker_parts_printed` | count | |
| `sensor.print_tracker_filament_used` | kg | |
| `sensor.print_tracker_energy_used` | kWh | |
| `sensor.print_tracker_total_cost` | currency | `wasted_cost` |
| `sensor.print_tracker_unrated_prints` | count | |
| `sensor.print_tracker_success_rate_30d` | % | |
| `sensor.print_tracker_failures_30d` | count | `top_reason` |
| `sensor.print_tracker_data_size` | MB | `database`, `git`, `thumbnails` |
| `sensor.print_tracker_project_<n>` | % | `done`, `target`, `parts`, `deadline`. One per active project |
| `sensor.print_tracker_<id>_spool_check` | `ok`, `warning` | required and remaining grams, warnings |
| `sensor.print_tracker_<id>_calibration_mismatches` | count | `mismatches` |
| `sensor.print_tracker_<id>_maint_<n>` | remaining, in the task's first unit | `percent_left`, `note`. With `binary_sensor` `..._due` and `button` `..._done` |
| `sensor.print_tracker_last_print` | status | `rating`, `failure_reason`, `calibration`, `project_line`, `job_id`, `file`, `parts`, `planned`, `excluded`, `minutes`, `grams`, `kwh`, `cost`, `cost_per_part`, `spool`, `changed_settings`, `url` |
| `sensor.print_tracker_recent_prints` | count | `jobs`: the last 10 rows |
| `sensor.print_tracker_top_parts` | distinct parts | `parts`, `excluded`: top 10 |
| `sensor.print_tracker_current_print_parts` | planned parts | `printed`, `excluded`, `file`. Available only while printing |
| `event.print_tracker_print_finished` | `completed`, `cancelled`, `error`, `rated` | the same data as Last print, `printer_id` |
| `button.print_tracker_rescan_history` | | checks Moonraker for finished jobs that are missing |

Print events wait in the database when the broker or Home Assistant is down, and go out after they return. Two more events go straight to HA's bus and are lost while HA is down, sensors keep their state: `klipper_print_tracker_spool_warning` and `klipper_print_tracker_maintenance_due`.

## Notification blueprints

Import `home-assistant/blueprints/automation/print_finished_notification.yaml` (the link is in the repository README), then create an automation from it. Choose the phone, and optionally a camera, the statuses and a printer. Tapping the notification opens the print's page. `maintenance_due_notification.yaml` in the same folder sends maintenance reminders.

Home Assistant doesn't update imported blueprints on its own. After updating the add-on, import them again with **Re-import blueprint**, or the new buttons won't appear.

## Rating prints

The notification carries the buttons and the add-on reads your taps from HA's event bus, so no other automation is needed. A tap made while the add-on is stopped is lost, the print page can do everything too.

- **Completed:** Добре, Погано, Нотатка (typed text).
- **Cancelled or failed:** Android shows at most 3 actions, so it gets Відклеїлось, Спагеті / зсув and Інше with typed text. Text with "засмічення" or "екструзія" is filed under the clog reason. iOS also gets the fourth button.

Action ids look like `KPT_<printer_id>_<job_id>_<code>`. The tag list is editable on any print page.

## Spool check

When a print starts, the add-on compares the print with the active spool: enough filament including the margin, no spool set, a different material, and, for information only, a preset that doesn't look like the spool. Spool names rarely match presets exactly, so that one never pauses anything. Without Spoolman in Moonraker the check stays silent.

On a problem it fires `klipper_print_tracker_spool_warning` and the blueprint offers Пауза and Продовжити. Pause runs the printer's own `PAUSE`.

## Maintenance

Each task has limits in print hours, days, grams, prints and abrasive grams, and the first one reached makes it due. Failed prints count, the machine moved anyway. On first use the page asks when tasks were last done, with today as the default, so nothing starts out overdue. Tasks becoming due mid-print are announced after the print ends. Defaults are generic for CoreXY and Creality K1 machines, edit or delete what doesn't suit you.

## Failure analysis

Stopped prints keep their progress, layer, chamber temperature when the printer has such a sensor, and how they stopped: cancelled, a Klipper error with its message, or `power_or_offline` (Klipper shutdown, lost connection mid-print, or the energy counter at 0). Power cuts stay out of reliability numbers unless you turn them on with the filter on the Аналіз page.

## Calibration log

OrcaSlicer's calibration models keep their name in the G-code, for example `temperature_tower.drc`, and that's the main signal. The range comes from the G-code where it's there:

| Test | Detected by | Range |
|---|---|---|
| Temperature tower | model name, confirmed on a real file | from `M104` |
| Retraction | `; Calib_Retraction_tower` comment | yes |
| PA pattern | `; start pressure advance pattern` comment | from `SET_PRESSURE_ADVANCE` |
| PA tower, PA line | model name or changing `SET_PRESSURE_ADVANCE` | yes |
| Flow, max volumetric speed, VFA | model name only, these tests leave no other mark | no |

Everything except the temperature tower comes from reading OrcaSlicer's source and is not yet confirmed on real files. If a test isn't recognised, use **Позначити як калібрування** on the print page.

Enter the value you picked from the notification (Ввести результат) or on the print page. The Калібрування page then shows the latest value per filament preset, warns when recent prints use a different value, and suggests repeating a calibration after `calibration_stale_days` or on a new spool.

## Projects

A project has target parts, and optional rules that claim finished prints by file name or part name (`ShoeRack*`). A print counts toward one project, and you can move it by hand on its page. Only completed prints add parts, failed attempts show up in the costs.

## Storage

Nothing here captures photos or video. Thumbnails stay small, `thumbnail_retention_days` limits them, `git gc --auto` runs weekly, and `sensor.print_tracker_data_size` shows the total.

## Deep links

`url` in entities and events has this format:

```
/app/<slug>/job/<printer_id>:<job_id>
```

`<slug>` includes the repository prefix, so it differs between installs. Take it from `url` or from the add-on log, don't type it by hand.

Home Assistant always loads the panel at its root, the rest of the path stays in the browser's address. The page reads it from there on the first load, and from the panel's `home-assistant/properties` message when the panel is already open. This needs Home Assistant 2026.2 or newer. Other pages work the same way: `/compare/<a>/<b>`, `/part/<name>`, `/preset/<type>/<name>`.

Inside the add-on, pages use a hash: `#/job/<printer_id>:<job_id>`. `direct_url` has the form `<direct_url option>/#/job/<printer_id>:<job_id>`.

## Direct port

The web UI is also available on port `8100/tcp`, for example over Tailscale. It's off by default: set a host port in the add-on's **Network** section. The direct port has no login, so it's read-only, and it should stay on a private network.

## API

`GET api/jobs`, `api/jobs.csv`, `api/job/<id>`, `api/compare/<a>/<b>`, `api/stats`, `api/health`, and `POST api/reconcile`. `api/jobs` takes `file`, `status`, `preset`, `spool`, `from`, `to`, `limit` and `offset`.

## Settings history

For each finished job the add-on reads the end of the G-code from Moonraker and stores the slicer's config block. A commit goes into `/data/git/<printer_id>` when the config changed. It's a normal repository per printer with `effective.ini` and `presets/{process,filament,printer}/<name>.ini`. Only the filaments the print really used get a preset file. Host and API key settings are dropped, if a slicer embeds any.

Labels, tabs and units come from OrcaSlicer's own sources, generated per version:

```
python -m app.slicer_meta generate --tag v2.4.2
```

Versions 2.3.2 and 2.4.2 are bundled. Others are generated at runtime and cached in `/data/layouts`, otherwise the nearest bundled version is used. Unknown keys and G-code from other slicers show up in the "Інші" tab.

## Backups

Everything lives in `/data` (`tracker.db`, `thumbs/`, `git/`, `layouts/`), which Home Assistant backups include. Before a database migration the add-on keeps a copy next to it as `tracker.db.pre-v<n>`.

## Troubleshooting

- **No entities:** check that the Mosquitto app and the MQTT integration are set up, then look for `No MQTT broker yet` in the log. The add-on keeps checking, so a broker added later is picked up. Tracking and the UI work without MQTT.
- **Parts are 0:** Exclude objects is off in the slicer.
- **No energy data:** check that `energy_sensor` exists and is a total counter. A print the add-on didn't see start has no energy value either, and so does a print started while Home Assistant was down.
- **"Settings aren't available" on a print:** the G-code was deleted from the printer before the print was finalised.
- **A note about incomplete exclusion data:** the add-on wasn't running when that print ended, so the record comes from Moonraker's history. Press **Rescan history** to pick up anything missing.
- **A deep link opens the start page:** check the Home Assistant version, then copy the exact `url` from `sensor.print_tracker_last_print`.

## UI development

No Moonraker or Home Assistant is needed. `python dev/serve.py` runs the UI on a seeded database (`--empty` for a fresh one). `/harness?theme=dark` loads the app in a frame with HA's variables on the parent, with `light` and `custom` as other themes. `dev/check_theme.js` and `dev/screenshots.js` drive it with Playwright. The `dev/` folder isn't part of the image.

## Licence note

The bundled `app/layouts/*.json` files contain text generated from OrcaSlicer's source and translations, which are licensed under AGPL-3.0. Icons in `app/static/icons.js` come from Material Design Icons (Apache-2.0).
