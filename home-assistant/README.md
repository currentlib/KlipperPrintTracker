# KlipperPrintTracker - Home Assistant files

**English** | [Українська](#українська)

Files for Home Assistant that go with the [Print Tracker add-on](../klipper_print_tracker/DOCS.md), plus the older YAML-only edition.

| File | What it is |
|---|---|
| `blueprints/automation/print_finished_notification.yaml` | Phone notification when a print ends, with rating buttons, and spool warnings |
| `blueprints/automation/maintenance_due_notification.yaml` | Maintenance reminder with Виконано and a 10 hour snooze |
| `dashboards/printer_dashboard.yaml` | Dashboard on top of the add-on's entities (sections view, standard cards only) |
| `packages/printer_extras.yaml` | Optional: pre-heat / cool-down scripts, fans-off and power-off automations |
| `lite/print_tracker.yaml` | The frozen YAML-only tracker, for Home Assistant without add-ons |

## With the add-on

1. Install the add-on and let it finish one print, or at least start, so its entities exist.
2. Import the blueprints (the button in the [root README](../README.md), or the raw file URL for the maintenance one), then create an automation from each. After an add-on update, use **Re-import blueprint**, Home Assistant doesn't do it for you.
3. Copy `packages/printer_extras.yaml` to `/config/packages/` if you want the extras, and replace the placeholders: `my_printer`, `switch.printer_plug`, `number.my_printer_output_pin_fan*`.
4. Paste `dashboards/printer_dashboard.yaml` into a new dashboard: Settings > Dashboards > Add dashboard > ⋮ > Raw configuration editor. Replace `my_printer`, `switch.printer_plug`, `sensor.printer_plug_power` and `sensor.printer_plug_energy_today`. The add-on's own entities don't need editing.

Cost on the dashboard uses `electricity_price` and `currency` from the add-on's options.

---

# Lite: YAML-only edition

This edition is frozen. Use it only if your Home Assistant can't run add-ons. It has no settings history and no web UI.

Track every 3D print in Home Assistant: printed and excluded parts, print status, duration, filament, energy, and cost per part. Nothing is installed on the printer and no slicer post-processing is needed: when a print ends, Home Assistant asks Moonraker for the details itself.

## Features

- **Real part counts.** Reads Klipper's `exclude_object` state, so objects you cancel mid-print are counted as excluded, not as printed. This fixes the main limitation of the printer-host version.
- **Every outcome is logged:** completed, cancelled, and failed prints.
- **Energy per print** from a smart plug's energy counter, plus its cost.
- **Filament cost** from the active Spoolman spool (read from Moonraker), with a fallback price per kg.
- **Cost per print and per part.**
- **Reliability stats:** success rate, money lost on failed prints, the most frequently excluded parts.
- **Per-part counters:** how many of each part you have printed in total.
- **Phone notification** with a camera snapshot, e.g. "Printed 4 of 5 parts, excluded: Bracket".
- **Google Sheets logging** (optional), through the official integration with no public Apps Script.

## Files

| File | What it is |
|---|---|
| `lite/print_tracker.yaml` | The tracker: helpers, Moonraker requests, history sensor, automation |

## Requirements

- Home Assistant 2024.10 or newer (sections view, `response_variable` in `rest_command`)
- [Moonraker integration](https://github.com/marcolivierarsenault/moonraker-home-assistant) (HACS)
- **Exclude objects** enabled in your slicer (OrcaSlicer: Others → Exclude objects)
- Optional: a smart plug with an energy counter (Tasmota, Shelly, etc.), the [Spoolman integration](https://github.com/Disane87/spoolman-homeassistant), the HA Companion app, the Google Sheets integration

## Installation

1. Enable packages in `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
2. Copy `lite/print_tracker.yaml` to `/config/packages/`.
3. Replace the placeholders (Find & Replace):

   | Placeholder | Replace with |
   |---|---|
   | `PRINTER_IP:7125` | Printer IP and Moonraker port. On Creality K1/K1C/K1 Max you can also use port `4408` |
   | `my_printer` | Entity prefix of your Moonraker integration (e.g. `sensor.my_printer_current_print_state`) |
   | `switch.printer_plug` | Smart plug switch |
   | `sensor.printer_plug_energy_total` | Plug's **total** energy counter in kWh (not "today", or prints past midnight break) |
   | `sensor.printer_plug_power`, `sensor.printer_plug_energy_today` | Plug power and today's energy (dashboard only) |
   | `notify.mobile_app_YOUR_PHONE` | Your phone's notify action |
   | `GOOGLE_SHEETS_ENTRY_ID` | `config_entry` of the Google Sheets integration (see below) |
   | `number.my_printer_output_pin_fan*` | Your fan `output_pin` entities (extras only) |

4. **Developer Tools → YAML → Check configuration → Restart.**
5. Set your electricity tariff and default filament price in the `Print Tracker - ...` helpers.

Don't paste the package into the automation editor. It is a package with helpers, sensors, and an automation, so the editor will reject it with `not a valid option at 'input_number'`.

## Google Sheets (optional)

1. Create a project in Google Cloud Console and enable the **Google Sheets API** and **Google Drive API**.
2. Google Auth Platform: fill in **Branding** (app name and emails). Under **Audience**, publish the app, otherwise tokens expire every 7 days. Publishing requires a home page and privacy policy URL.
3. **Clients → Create client → Web application**, redirect URI `https://my.home-assistant.io/redirect/oauth`.
4. In HA, add the credentials under **Settings → Devices & services → ⋮ → Application Credentials** first. The "Add credentials" popup in the integration flow often hangs.
5. Add the **Google Sheets** integration. It creates a new spreadsheet in your Drive and can only access that one.
6. Add a sheet named **`Друк HA`** to it, or change `worksheet:` in the package.
7. Get the `config_entry`: Developer Tools → Actions → `google_sheets.append_sheet` → select the spreadsheet → YAML mode.
8. Turn on `input_boolean.print_tracker_gsheets`.

## How it works

```
print starts      -> remember plug energy counter
every 2 min       -> snapshot exclude_object (fallback if Klipper resets it)
print ends        -> Moonraker: /printer/objects/query?exclude_object
                               /server/history/list?limit=1
                  -> count parts ("Bracket.stl_id_0_copy_2" -> "Bracket")
                  -> energy, filament, cost per print and per part
                  -> sensor.print_tracker, notification, Google Sheets
```

History lives in the attributes of `sensor.print_tracker` (a trigger-based template sensor), so it survives restarts. You may want to exclude `sensor.print_tracker` and `sensor.print_tracker_live` from `recorder` to keep the database small.

## Notes

- UI labels and notifications are in Ukrainian and the currency is UAH. Search for `грн` and the Ukrainian strings to translate.
- Active spool detection assumes Spoolman entities are named `sensor.spoolman_spool_<id>`, where `<id>` is the Spoolman spool ID.

---

## Українська

Файли для Home Assistant до [add-on Print Tracker](../klipper_print_tracker/DOCS.md): blueprint сповіщень, дашборд, `printer_extras.yaml` і заморожена версія лише на YAML у `lite/`.

**З add-on:** встанови add-on, імпортуй обидва blueprint (сповіщення про друк і `maintenance_due_notification.yaml`) і після оновлення add-on виконуй **Re-import blueprint**, бо HA не робить цього сам. Кнопкою з [кореневого README](../README.md) імпортується перший, скопіюй `packages/printer_extras.yaml` у `/config/packages/` за потреби, встав `dashboards/printer_dashboard.yaml` через Raw configuration editor і заміни плейсхолдери `my_printer`, `switch.printer_plug`, `sensor.printer_plug_power`, `sensor.printer_plug_energy_today`. Сутності самого add-on міняти не треба.

**Lite (заморожена версія, лише для HA без add-on):**

Облік кожного 3D-друку в Home Assistant: надруковані та виключені деталі, статус, тривалість, пластик, енергія і собівартість деталі. На принтер нічого не ставиться, post-processing у слайсері не потрібен: після завершення друку HA сам питає Moonraker.

**Можливості:** реальний підрахунок деталей з урахуванням виключених під час друку; облік успішних, скасованих і невдалих друків; енергія і її вартість за друк; вартість пластику з активної котушки Spoolman; собівартість друку і деталі; статистика надійності і найчастіше виключені деталі; лічильники по деталях; сповіщення з фото з камери; запис у Google Sheets (необовʼязково); дашборд.

**Встановлення:**
1. Увімкни packages у `configuration.yaml` (див. приклад вище).
2. Скопіюй `lite/print_tracker.yaml` у `/config/packages/`.
3. Заміни плейсхолдери з таблиці вище.
4. Інструменти розробника → YAML → Перевірити конфігурацію → Перезапустити.
5. Встанови тариф і ціну пластику в хелперах `Print Tracker - ...`.

Package не можна вставляти в редактор автоматизацій, бо це не автоматизація, а набір хелперів, сенсорів і автоматизації.

**Google Sheets:** кроки ті самі, що в англійському розділі. Головне: спочатку додай credentials через Application Credentials, бо попап в інтеграції часто зависає. Інтеграція створює власну таблицю, тож аркуш `Друк HA` треба додати в неї.
