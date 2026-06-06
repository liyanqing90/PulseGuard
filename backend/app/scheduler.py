from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import storage
from .config import TIMEZONE
from .runner import CheckRunner


class PulseScheduler:
    def __init__(self, runner: CheckRunner) -> None:
        self.runner = runner
        self.scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        self.scheduler.add_job(
            storage.cleanup_old_data,
            "interval",
            hours=24,
            id="cleanup-old-runs",
            replace_existing=True,
        )
        self.refresh_all()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def refresh_all(self) -> None:
        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith("check-"):
                self.scheduler.remove_job(job.id)
        for check in storage.list_checks(enabled_only=True):
            self.sync_check(int(check["id"]))

    def sync_check(self, check_id: int) -> None:
        job_id = self._job_id(check_id)
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        check = storage.get_check(check_id)
        if not check or not check.get("enabled"):
            return

        self.scheduler.add_job(
            self._run_scheduled,
            "interval",
            seconds=max(5, int(check.get("interval_seconds") or 300)),
            id=job_id,
            args=[check_id],
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    async def _run_scheduled(self, check_id: int) -> None:
        await self.runner.run_check(check_id, trigger="scheduled")

    @staticmethod
    def _job_id(check_id: int) -> str:
        return f"check-{check_id}"
