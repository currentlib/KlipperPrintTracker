# Klipper Print Tracker

Tracks every print on your Klipper printer and keeps a git history of the slicer settings used for it. The add-on talks to Moonraker directly: nothing is installed on the printer and the slicer needs no post-processing script.

## Install

1. Add this repository in **Settings > Apps > App store > Repositories**: `https://github.com/currentlib/KlipperPrintTracker`.
2. Install **Klipper Print Tracker**. Home Assistant builds the image on your device, so the first install takes a few minutes on a Raspberry Pi.
3. Set `moonraker_url` in the options and start the add-on.
4. Turn on **Show in sidebar**.

For part counts, enable **Exclude objects** in your slicer (OrcaSlicer: Others > Exclude objects).

The add-on starts empty and only records jobs that finish after its first start.

## Options

| Option | Description |
|---|---|
| `moonraker_url` | For example `http://192.168.1.50:7125`. Creality K1 series printers also work on port `4408` |
| `printer_name` | Used in the MQTT device name |
| `energy_sensor` | Entity ID of a **total** energy counter in kWh. A daily counter breaks on prints past midnight |
| `electricity_price` | Price per kWh |
| `default_filament_price` | Price per kg, used when Spoolman has no price |
| `currency` | Display only |
| `google_sheets_config_entry` | When set, a row is appended for every print |
| `google_sheets_worksheet` | The worksheet must already exist |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | Only needed without the Mosquitto app |
| `direct_url` | Address of the optional direct port, adds `direct_url` to entities and events |
| `auto_fetch_layouts` | Generate slicer metadata at runtime for OrcaSlicer versions that aren't bundled |
| `log_level` | Log detail |

## Entities

With the Mosquitto app and the MQTT integration, the add-on creates the device **Print Tracker (printer name)**. Entity IDs are fixed so the dashboard works without editing.

| Entity | State | Attributes |
|---|---|---|
| `sensor.print_tracker_total_prints` | count | completed, cancelled, failed and the other totals |
| `sensor.print_tracker_success_rate` | % | |
| `sensor.print_tracker_parts_printed` | count | |
| `sensor.print_tracker_filament_used` | kg | |
| `sensor.print_tracker_energy_used` | kWh | |
| `sensor.print_tracker_total_cost` | currency | `wasted_cost` |
| `sensor.print_tracker_last_print` | status | `job_id`, `file`, `parts`, `planned`, `excluded`, `minutes`, `grams`, `kwh`, `cost`, `cost_per_part`, `spool`, `changed_settings`, `url` |
| `sensor.print_tracker_recent_prints` | count | `jobs`: the last 10 rows |
| `sensor.print_tracker_top_parts` | distinct parts | `parts`, `excluded`: top 10 |
| `sensor.print_tracker_current_print_parts` | planned parts | `printed`, `excluded`, `file`. Available only while printing |
| `event.print_tracker_print_finished` | `completed`, `cancelled`, `error` | the same data as Last print |
| `button.print_tracker_rescan_history` | | checks Moonraker for finished jobs that are missing |

Events wait in the database when the broker or Home Assistant is down, and go out after they return.

## Notification blueprint

Import `home-assistant/blueprints/automation/print_finished_notification.yaml` (the link is in the repository README), then create an automation from it. Choose the phone, and optionally a camera and the statuses. Tapping the notification opens the print's page.

## Deep links

`url` in entities and events has this format:

```
/app/<slug>/job/<job_id>
```

`<slug>` includes the repository prefix, so it differs between installs. Take it from `url` or from the add-on log, don't type it by hand.

Home Assistant always loads the panel at its root, the rest of the path stays in the browser's address. The page reads it from there on the first load, and from the panel's `home-assistant/properties` message when the panel is already open. This needs Home Assistant 2026.2 or newer. Other pages work the same way: `/compare/<a>/<b>`, `/part/<name>`, `/preset/<type>/<name>`.

Inside the add-on, pages use a hash: `#/job/<job_id>`. `direct_url` has the form `<direct_url option>/#/job/<job_id>`.

## Direct port

The web UI is also available on port `8100/tcp`, for example over Tailscale. It's off by default: set a host port in the add-on's **Network** section. The direct port has no login, so it's read-only, and it should stay on a private network.

## API

`GET api/jobs`, `api/jobs.csv`, `api/job/<id>`, `api/compare/<a>/<b>`, `api/stats`, `api/health`, and `POST api/reconcile`. `api/jobs` takes `file`, `status`, `preset`, `spool`, `from`, `to`, `limit` and `offset`.

## Settings history

For each finished job the add-on reads the end of the G-code from Moonraker and stores the slicer's config block. A commit goes into `/data/git` when the config changed. It's a normal repository with `effective.ini` and `presets/{process,filament,printer}/<name>.ini`. Only the filaments the print really used get a preset file. Host and API key settings are dropped, if a slicer embeds any.

Labels, tabs and units come from OrcaSlicer's own sources, generated per version:

```
python -m app.slicer_meta generate --tag v2.4.2
```

Versions 2.3.2 and 2.4.2 are bundled. Others are generated at runtime and cached in `/data/layouts`, otherwise the nearest bundled version is used. Unknown keys and G-code from other slicers show up in the "Інші" tab.

## Backups

Everything lives in `/data` (`tracker.db`, `thumbs/`, `git/`, `layouts/`), which Home Assistant backups include.

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
