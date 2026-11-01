from app.config import Options
from app.links import Links
from app.sheets import GoogleSheets
from app.summary import sheet_row

LINKS = Links("slug_x", external_base="https://ha.example/")
RECORD = {"job_id": "000001", "filename": "plate.gcode", "status": "completed", "end_time": 1000.0,
          "printed": {"Bracket": 3, "Clip": 1}, "excluded": {"Bracket": 1}, "parts": 4, "planned": 5,
          "print_duration": 3660, "grams": 10, "kwh": None}


class Supervisor:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    async def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))
        return self.result


def test_sheet_row_columns():
    row = sheet_row(RECORD, LINKS)
    assert list(row) == ["Date", "File", "Status", "Parts", "Planned", "Printed per part", "Excluded",
                         "Minutes", "Grams", "Spool", "kWh", "Energy cost", "Filament cost", "Total",
                         "Cost per part", "Job ID", "Link", "Changed settings"]
    assert row["Printed per part"] == "Bracket x3, Clip x1"
    assert row["Link"] == "https://ha.example/app/slug_x/job/printer1:000001"
    assert row["kWh"] == "" and row["Minutes"] == 61


async def test_append_only_when_configured():
    supervisor = Supervisor()
    await GoogleSheets(Options(), supervisor, LINKS).job_finished(RECORD)
    assert supervisor.calls == []
    options = Options(google_sheets_config_entry="ENTRY", google_sheets_worksheet="Log")
    await GoogleSheets(options, supervisor, LINKS).job_finished(RECORD)
    domain, service, data = supervisor.calls[0]
    assert (domain, service) == ("google_sheets", "append_sheet")
    assert data["config_entry"] == "ENTRY" and data["worksheet"] == "Log"


async def test_failure_doesnt_raise():
    options = Options(google_sheets_config_entry="ENTRY")
    await GoogleSheets(options, Supervisor(result=False), LINKS).job_finished(RECORD)
