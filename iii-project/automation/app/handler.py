import os
from datetime import UTC, datetime

from mangum import Mangum

from app.main import app
from app.messaging import SesMessenger, SimulationMessenger, SnsMessenger
from app.repositories import DynamoRepository
from app.scheduler import AutomationScheduler


api_handler = Mangum(app)


def run_scheduled_cycle() -> dict[str, int]:
    mode = os.getenv("OUTREACH_MODE", "simulation")
    if mode == "email":
        messenger = SesMessenger()
    elif mode == "sms":
        messenger = SnsMessenger()
    else:
        messenger = SimulationMessenger()
    clock = lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    scheduler = AutomationScheduler(
        DynamoRepository(clock=clock),
        messenger,
        clock,
        mode=mode,
        auto_approve=os.getenv(
            "AUTO_APPROVE_OUTREACH",
            "true",
        ).casefold()
        == "true",
        max_cases=int(os.getenv("MAX_CASES_PER_RUN", "25")),
    )
    return scheduler.run()


def handler(event, context):
    if event.get("source") == "carecircle.scheduler":
        return {
            "ok": True,
            "trigger": "eventbridge",
            "summary": run_scheduled_cycle(),
        }
    return api_handler(event, context)
