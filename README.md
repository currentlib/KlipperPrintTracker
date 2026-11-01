# KlipperPrintTracker

**English** | [Українська](#українська)

**Klipper-focused 3D print tracker** that counts the parts you print and logs print outcomes.

The project comes in two editions. They solve the same problem in different places: one runs on the printer host and relies on the slicer, the other runs entirely in Home Assistant and asks Moonraker for the details when a print ends.

---

## Editions

| | printer-host | home-assistant |
|---|---|---|
| Runs on | Klipper host + slicer post-processing | Home Assistant |
| Install on printer | gcode_shell_command plugin + scripts | nothing |
| Slicer setup | post-processing script on every PC | only "Exclude objects" |
| Parts excluded mid-print | not tracked | tracked |
| Cancelled / failed prints | not logged | logged |
| Energy, filament, cost per part | no | yes |
| Storage | Google Sheets via public Apps Script | HA sensor + optional Google Sheets integration |
| Notifications | no | yes, with camera snapshot |

---

## Which one should I use?

- **home-assistant** if you run Home Assistant with the Moonraker integration.
- **printer-host** if you don't use Home Assistant.

---

## Setup

- [printer-host/README.md](printer-host/README.md)
- [home-assistant/README.md](home-assistant/README.md)

---

## Result

Google Sheet filled by the printer-host edition:

![Screenshot of the final sheet.](printer-host/img/gsheet_sample.png)


# Українська

**Трекер 3D-друку з фокусом на Klipper**, який рахує надруковані деталі та логує результати друку.

Проєкт має дві версії. Вони вирішують одну задачу, але в різних місцях: перша працює на хості принтера і залежить від слайсера, друга повністю живе в Home Assistant і сама питає Moonraker про деталі після завершення друку.

---

## Версії

| | printer-host | home-assistant |
|---|---|---|
| Де працює | Хост Klipper + постобробка у слайсері | Home Assistant |
| Що ставити на принтер | плагін gcode_shell_command + скрипти | нічого |
| Налаштування слайсера | скрипт постобробки на кожному ПК | лише "Exclude objects" |
| Деталі, виключені під час друку | не враховуються | враховуються |
| Скасовані / невдалі друки | не логуються | логуються |
| Енергія, пластик, собівартість деталі | ні | так |
| Зберігання | Google Sheets через публічний Apps Script | сенсор HA + необов'язкова інтеграція Google Sheets |
| Сповіщення | ні | так, з фото з камери |

---

## Яку версію обрати?

- **home-assistant**, якщо у вас є Home Assistant з інтеграцією Moonraker.
- **printer-host**, якщо ви не користуєтесь Home Assistant.

---

## Налаштування

- [printer-host/README.md](printer-host/README.md)
- [home-assistant/README.md](home-assistant/README.md)

---

## Результат

Google Таблиця, заповнена версією printer-host:

![Screenshot of the final sheet.](printer-host/img/gsheet_sample.png)
