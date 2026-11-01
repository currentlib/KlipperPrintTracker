"""Optional Google Sheets log through Home Assistant's integration."""
import logging

from .summary import sheet_row

log = logging.getLogger(__name__)


class GoogleSheets:
    def __init__(self, options, supervisor, links):
        self.options = options
        self.supervisor = supervisor
        self.links = links

    async def current(self, active):
        pass

    async def job_finished(self, record: dict):
        if not self.options.google_sheets_config_entry:
            return
        ok = await self.supervisor.call_service("google_sheets", "append_sheet", {
            "config_entry": self.options.google_sheets_config_entry,
            "worksheet": self.options.google_sheets_worksheet,
            "data": sheet_row(record, self.links),
        })
        if not ok:
            log.warning("Google Sheets row for job %s wasn't written", record["job_id"])
