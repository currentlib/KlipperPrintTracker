# KlipperPrintTracker

**English** | [Українська](#українська)

**Klipper-focused 3D print tracker** that counts the parts you print, logs print outcomes and keeps a history of the slicer settings behind every print.

The main edition is a Home Assistant add-on. It watches Moonraker on its own, so there's nothing to install on the printer and nothing to set up in the slicer beyond "Exclude objects". Every print gets a record with status, printed and excluded parts, time, filament, energy and cost, plus the exact slicer settings it used, a git history of them and diffs between prints.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcurrentlib%2FKlipperPrintTracker)
[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Fcurrentlib%2FKlipperPrintTracker%2Fmain%2Fhome-assistant%2Fblueprints%2Fautomation%2Fprint_finished_notification.yaml)

---

## Editions

| | Add-on (recommended) | Lite YAML | printer-host |
|---|---|---|---|
| For | Home Assistant OS or Supervised | HA without add-ons | no Home Assistant |
| Runs on | HA add-on | HA package | Klipper host + slicer post-processing |
| Install on printer | nothing | nothing | gcode_shell_command plugin + scripts |
| Slicer setup | only "Exclude objects" | only "Exclude objects" | post-processing script on every PC |
| Parts excluded mid-print | tracked | tracked | not tracked |
| Cancelled / failed prints | logged | logged | not logged |
| Energy, filament, cost per part | yes | yes | no |
| Slicer settings history | yes, with git and diffs | no | no |
| Web UI | yes, inside HA | dashboard only | no |
| Storage | SQLite, git, optional Google Sheets | HA sensor, optional Google Sheets | Google Sheets via public Apps Script |
| Notifications | yes, through a blueprint | yes | no |
| Status | active | frozen | legacy |

---

## Which one should I use?

- **Add-on** if you run Home Assistant OS with the Moonraker printer on your network.
- **Lite YAML** if your Home Assistant can't run add-ons (a Container install, for example).
- **printer-host** if you don't use Home Assistant.

---

## Setup

- Add-on: [klipper_print_tracker/DOCS.md](klipper_print_tracker/DOCS.md)
- Blueprint, dashboard and lite YAML: [home-assistant/README.md](home-assistant/README.md)
- Legacy scripts: [printer-host/README.md](printer-host/README.md)

---

## Development

The tests need `pytest`, `pytest-asyncio`, `pyyaml`, `jinja2` and `amqtt`:

```
cd klipper_print_tracker
pip install -r requirements.txt pytest pytest-asyncio pyyaml jinja2 amqtt
pytest
```

---

## Result

Google Sheet filled by the printer-host edition:

![Screenshot of the final sheet.](printer-host/img/gsheet_sample.png)


# Українська

**Трекер 3D-друку з фокусом на Klipper**, який рахує надруковані деталі, логує результати друку і зберігає історію налаштувань слайсера для кожного друку.

Основна версія проєкту це add-on для Home Assistant. Він сам стежить за Moonraker, тому на принтер нічого не ставиться, а в слайсері достатньо ввімкнути "Exclude objects". Кожен друк отримує запис зі статусом, надрукованими і виключеними деталями, часом, пластиком, енергією та вартістю, а також точні налаштування слайсера, їхню git-історію і порівняння між друками.

---

## Версії

| | Add-on (рекомендовано) | Lite YAML | printer-host |
|---|---|---|---|
| Для кого | Home Assistant OS або Supervised | HA без add-on | без Home Assistant |
| Де працює | add-on у HA | package у HA | Хост Klipper + постобробка у слайсері |
| Що ставити на принтер | нічого | нічого | плагін gcode_shell_command + скрипти |
| Налаштування слайсера | лише "Exclude objects" | лише "Exclude objects" | скрипт постобробки на кожному ПК |
| Деталі, виключені під час друку | враховуються | враховуються | не враховуються |
| Скасовані / невдалі друки | логуються | логуються | не логуються |
| Енергія, пластик, собівартість деталі | так | так | ні |
| Історія налаштувань слайсера | так, з git і порівнянням | ні | ні |
| Вебінтерфейс | так, усередині HA | лише дашборд | ні |
| Зберігання | SQLite, git, необов'язково Google Sheets | сенсор HA, необов'язково Google Sheets | Google Sheets через публічний Apps Script |
| Сповіщення | так, через blueprint | так | ні |
| Статус | активний | заморожений | застарілий |

---

## Яку версію обрати?

- **Add-on**, якщо у вас Home Assistant OS і принтер з Moonraker у вашій мережі.
- **Lite YAML**, якщо ваш Home Assistant не підтримує add-on (наприклад, встановлений у контейнері).
- **printer-host**, якщо ви не користуєтесь Home Assistant.

---

## Налаштування

- Add-on: [klipper_print_tracker/DOCS.md](klipper_print_tracker/DOCS.md)
- Blueprint, дашборд і lite YAML: [home-assistant/README.md](home-assistant/README.md)
- Старі скрипти: [printer-host/README.md](printer-host/README.md)
