"""Every outward link is built here."""
from urllib.parse import quote


class Links:
    """`url` opens a page inside Home Assistant, `direct_url` over the optional direct port."""

    def __init__(self, slug: str, direct_base: str | None = None, external_base: str | None = None):
        self.slug = slug
        self.direct_base = direct_base
        self.external_base = external_base

    def panel(self) -> str:
        return f"/app/{self.slug}"

    def job(self, job_id: str) -> str:
        return f"{self.panel()}/job/{quote(str(job_id), safe='')}"

    def direct_job(self, job_id: str) -> str | None:
        if not self.direct_base:
            return None
        return f"{self.direct_base}/#/job/{quote(str(job_id), safe='')}"

    def absolute_job(self, job_id: str) -> str:
        """For places outside the HA frontend, like a spreadsheet."""
        return (self.external_base or "").rstrip("/") + self.job(job_id)
