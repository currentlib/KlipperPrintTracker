"""Every outward link is built here."""
from urllib.parse import quote

from .config import DEFAULT_PRINTER


def job_ref(job_id: str, printer_id: str = DEFAULT_PRINTER) -> str:
    """Identifies a print across printers in URLs: printer1:000042."""
    return f"{printer_id}:{quote(str(job_id), safe='')}"


class Links:
    """`url` opens a page inside Home Assistant, `direct_url` over the optional direct port."""

    def __init__(self, slug: str, direct_base: str | None = None, external_base: str | None = None):
        self.slug = slug
        self.direct_base = direct_base
        self.external_base = external_base

    def panel(self) -> str:
        return f"/app/{self.slug}"

    def job(self, job_id: str, printer_id: str = DEFAULT_PRINTER) -> str:
        return f"{self.panel()}/job/{job_ref(job_id, printer_id)}"

    def direct_job(self, job_id: str, printer_id: str = DEFAULT_PRINTER) -> str | None:
        if not self.direct_base:
            return None
        return f"{self.direct_base}/#/job/{job_ref(job_id, printer_id)}"

    def absolute_job(self, job_id: str, printer_id: str = DEFAULT_PRINTER) -> str:
        """For places outside the HA frontend, like a spreadsheet."""
        return (self.external_base or "").rstrip("/") + self.job(job_id, printer_id)
