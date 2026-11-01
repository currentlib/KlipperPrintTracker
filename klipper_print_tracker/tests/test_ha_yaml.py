from datetime import datetime, timezone
from pathlib import Path

import jinja2
import pytest
import yaml

ROOT = Path(__file__).parents[2]
BLUEPRINT = ROOT / "home-assistant/blueprints/automation/print_finished_notification.yaml"
DASHBOARD = ROOT / "home-assistant/dashboards/printer_dashboard.yaml"


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda loader, node: {"input": loader.construct_scalar(node)})


def env(states=None, attrs=None):
    environment = jinja2.Environment(undefined=jinja2.ChainableUndefined, extensions=["jinja2.ext.loopcontrols"])
    states, attrs = states or {}, attrs or {}

    def to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def to_int(value, default=0):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    moment = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    environment.filters.update(float=to_float, int=to_int, as_local=lambda v: v,
                               as_timestamp=lambda v: v.timestamp() if isinstance(v, datetime) else moment.timestamp(),
                               timestamp_custom=lambda v, f: "12:00", is_number=lambda v: True)
    environment.globals.update(
        states=lambda e: states.get(e, "unknown"), state_attr=lambda e, a: attrs.get(e, {}).get(a),
        is_state=lambda e, s: states.get(e) == s, now=lambda: moment,
        as_timestamp=lambda v: moment.timestamp() if not isinstance(v, datetime) else v.timestamp())
    return environment


def render(template, variables=None, **kwargs):
    return env(**kwargs).from_string(template).render(**(variables or {}))


def blueprint():
    return yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=Loader)


JOB = {"event_type": "completed", "file": "plate", "parts": 4, "planned": 5, "excluded": "Bracket",
       "minutes": 125, "grams": 42.5, "kwh": 0.4, "cost": 90, "cost_per_part": 22.5, "currency": "UAH",
       "changed_settings": ["flow_ratio", "outer_wall_speed"], "url": "/app/slug/job/000001"}


def message(job, include_changes=True):
    data = blueprint()["variables"]
    return render(data["notification_message"], {"job": job, "status": job["event_type"],
                                                 "include_changes": include_changes})


def test_blueprint_structure():
    data = blueprint()
    inputs = data["blueprint"]["input"]
    assert set(inputs) == {"event_entity", "notify_device", "camera", "statuses", "include_changes", "printer_filter", "spool_warnings"}
    assert data["blueprint"]["domain"] == "automation"
    assert data["triggers"][0]["entity_id"] == {"input": "event_entity"}
    assert inputs["notify_device"]["selector"]["device"]["filter"][0]["integration"] == "mobile_app"
    assert {t["id"] for t in data["triggers"]} == {"finished", "spool"}
    for branch in ("then", "else"):
        action = data["actions"][1][branch][0]
        assert action["domain"] == "mobile_app" and action["type"] == "notify"
        assert action["data"]["clickAction"] == action["data"]["url"] == "{{ job.url }}"
    assert data["actions"][1]["then"][0]["data"]["image"].startswith("/api/camera_proxy/")


def test_message_with_excluded_part_and_changes():
    text = message(JOB)
    assert text.splitlines()[0] == "plate"
    assert "Надруковано 4 з 5 деталей, виключено: Bracket" in text
    assert "⏱️ 2 год 5 хв · 🧵 42.5 г · ⚡ 0.4 кВт·год" in text
    assert "💸 90 UAH (22.5 UAH/шт)" in text
    assert "⚙️ Змінено з минулого друку: flow_ratio, outer_wall_speed" in text


def test_message_toggle_and_missing_energy():
    text = message({**JOB, "kwh": None}, include_changes=False)
    assert "⚙️" not in text and "кВт·год" not in text


def test_message_cancelled():
    text = message({**JOB, "event_type": "cancelled", "parts": 0, "excluded": "", "cost_per_part": 0})
    assert "Зупинено через 2 год 5 хв" in text and "/шт" not in text


@pytest.mark.parametrize("parts,word", [(1, "деталь"), (3, "деталі"), (7, "деталей")])
def test_message_plurals(parts, word):
    assert f"Надруковано {parts} {word}" in message({**JOB, "parts": parts, "excluded": ""})


@pytest.mark.parametrize("status,title", [("completed", "✅ Друк завершено"), ("error", "❌ Помилка друку")])
def test_title(status, title):
    template = blueprint()["variables"]["notification_title"]
    assert render(template, {"status": status}).strip() == title


def actions(job, apple=False):
    data = blueprint()["variables"]
    environment = env()
    environment.globals["device_attr"] = lambda device, key: "Apple" if apple else "Google"
    context = {"job": job, "status": job["event_type"], "notify_device": "d", "is_apple": apple,
               "action_prefix": f"KPT_{job['printer_id']}_{job['job_id']}_"}
    return yaml.safe_load(environment.from_string(data["notification_actions"]).render(**context).strip())


JOB_IDS = {"printer_id": "printer1", "job_id": "00004F"}


def test_rating_actions_after_a_completed_print():
    items = actions({**JOB, **JOB_IDS})
    assert [a["action"] for a in items] == ["KPT_printer1_00004F_good", "KPT_printer1_00004F_bad", "KPT_printer1_00004F_note"]
    assert items[2]["behavior"] == "textInput"


def test_failure_actions_fit_android():
    items = actions({**JOB, **JOB_IDS, "event_type": "cancelled"})
    assert len(items) == 3
    assert [a["action"].rsplit("_", 1)[1] for a in items] == ["fail-adhesion", "fail-spaghetti", "fail-other"]


def test_failure_actions_on_ios_have_every_reason():
    items = actions({**JOB, **JOB_IDS, "event_type": "error"}, apple=True)
    assert [a["title"] for a in items][2] == "Засмічення / недоекструзія" and len(items) == 4


def test_spool_message():
    template = blueprint()["variables"]["spool_message"]
    trigger = {"id": "spool", "event": {"data": {"file": "a.gcode", "warnings": [
        {"code": "not_enough", "required_g": 80, "remaining_g": 40}, {"code": "preset_mismatch", "info": True},
        {"code": "material_mismatch", "wanted": "PETG", "actual": "PLA"}]}}}
    text = render(template, {"trigger": trigger})
    assert "потрібно 80 г, лишилось 40 г" in text and "у G-code PETG, на котушці PLA" in text
    assert "preset" not in text and render(template, {"trigger": {"id": "finished"}}).strip() == ""


def test_rated_events_dont_break_the_title():
    template = blueprint()["variables"]["notification_title"]
    assert render(template, {"status": "rated"}).strip() == ""


def cards(node):
    if isinstance(node, dict):
        if node.get("type") == "markdown":
            yield node
        for value in node.values():
            yield from cards(value)
    elif isinstance(node, list):
        for value in node:
            yield from cards(value)


def dashboard():
    return yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))


STATS = {"total": 3, "completed": 2, "cancelled": 1, "failed": 0, "success_rate": 66.7, "parts": 9,
         "filament_kg": 0.1, "kwh": 1.2, "total_cost": 100, "wasted_cost": 10, "currency": "UAH",
         "panel_url": "/app/slug", "electricity_price": 4.32}
ATTRS = {
    "sensor.print_tracker_total_prints": STATS,
    "sensor.print_tracker_recent_prints": {"jobs": [
        {"date": "01.11 10:00", "file": "plate", "status": "completed", "parts": 4, "planned": 5, "excluded": True,
         "minutes": 65, "grams": 10, "cost": 20, "per_part": 5, "spool": "PETG", "url": "/app/slug/job/1"}]},
    "sensor.print_tracker_top_parts": {"parts": [{"name": "Bracket", "count": 5}],
                                       "excluded": [{"name": "Clip", "count": 1, "rate": 25.0}]},
}
STATES = {"sensor.my_printer_current_print_state": "printing", "sensor.my_printer_progress": "42",
          "sensor.printer_plug_energy_today": "2", "switch.printer_plug": "on",
          "sensor.my_printer_print_eta": "2026-11-01T13:00:00+00:00"}


class Stamp:
    last_changed = datetime(2026, 11, 1, 11, 55, tzinfo=timezone.utc)


def rendered_history(**kwargs):
    outputs = []
    for card in cards(dashboard()):
        outputs.append(render(card["content"], {"states": _StatesProxy(kwargs.get("states"))}, **kwargs))
    return "\n".join(outputs)


class _StatesProxy:
    """Supports both states('x') and states.sensor.x in templates."""

    def __init__(self, values):
        self.values = values or {}
        self.sensor = type("S", (), {"my_printer_current_print_state": Stamp()})

    def __call__(self, entity):
        return self.values.get(entity, "unknown")


def test_dashboard_renders_with_data():
    text = rendered_history(states=STATES, attrs=ATTRS)
    assert "| **3** | 2 | 1 | 0 | **66.7%** |" in text
    assert "[⚙️](/app/slug/job/1)" in text and "4/5 ⚠️" in text and "1:05" in text
    assert "| Bracket | **5** |" in text and "| Clip | **1** | 25% |" in text
    assert "[📂 Відкрити Print Tracker](/app/slug)" in text
    assert "8.64 UAH" in text


def test_dashboard_renders_without_data():
    text = rendered_history(states={}, attrs={})
    assert "Ще немає жодного запису" in text and "Поки порожньо." in text
    assert "ще не опублікував дані" in text


def test_dashboard_has_no_replaced_helpers():
    text = DASHBOARD.read_text(encoding="utf-8")
    assert "input_number." not in text and "input_boolean." not in text
    assert "'sensor.print_tracker'" not in text and "sensor.print_tracker\n" not in text
    assert "sensor.printer_active_spool" not in text and "print_tracker_live" not in text


def test_lite_is_marked_frozen():
    lite = (ROOT / "home-assistant/lite/print_tracker.yaml").read_text(encoding="utf-8")
    assert lite.startswith("# ====") and "FROZEN" in lite[:200]
    assert yaml.safe_load(lite)["automation"][0]["id"] == "print_tracker"
    assert not (ROOT / "home-assistant/packages/print_tracker.yaml").exists()
