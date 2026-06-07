from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from app.messaging import Messenger
from app.models import Approval, CaseRecord, CaseState, EscalationTask
from app.ranking import rank_donors
from app.repositories import CaseRepository
from app.services import OutreachService
from app.workflow import transition


class AutomationScheduler:
    def __init__(
        self,
        repo: CaseRepository,
        messenger: Messenger,
        clock: Callable[[], str],
        *,
        mode: str = "simulation",
        auto_approve: bool = True,
        max_cases: int = 25,
    ) -> None:
        self.repo = repo
        self.messenger = messenger
        self.clock = clock
        self.mode = mode
        self.auto_approve = auto_approve
        self.max_cases = max_cases

    def run(self) -> dict[str, int]:
        summary = {
            "processed": 0,
            "planned": 0,
            "outreach_started": 0,
            "follow_ups": 0,
            "escalations": 0,
            "coordinating": 0,
            "expired": 0,
            "skipped": 0,
        }
        active_states = {
            CaseState.DRAFT,
            CaseState.NEEDS_INFORMATION,
            CaseState.PLANNED,
            CaseState.AWAITING_APPROVAL,
            CaseState.OUTREACH_ACTIVE,
            CaseState.DONOR_CONFIRMED,
        }
        cases = [
            case
            for case in self.repo.list_cases()
            if case.state in active_states
        ][: self.max_cases]

        for case in cases:
            summary["processed"] += 1
            self._process_case(case, summary)
        return summary

    def _process_case(
        self,
        case: CaseRecord,
        summary: dict[str, int],
    ) -> None:
        now = datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
        if case.request.deadline < now.date() and case.state in {
            CaseState.NEEDS_INFORMATION,
            CaseState.OUTREACH_ACTIVE,
        }:
            self._move(
                case,
                CaseState.EXPIRED,
                "CASE_EXPIRED",
                {"reason": "deadline_passed", "automated": True},
            )
            summary["expired"] += 1
            return

        if case.state is CaseState.DRAFT:
            case = self._move(
                case,
                CaseState.PLANNED,
                "CASE_PLANNED",
                {"automated": True},
            )
            summary["planned"] += 1
            if self._start_outreach(case):
                summary["escalations"] += 1
            summary["outreach_started"] += 1
            return

        if case.state in {
            CaseState.PLANNED,
            CaseState.AWAITING_APPROVAL,
        }:
            if self._start_outreach(case):
                summary["escalations"] += 1
            summary["outreach_started"] += 1
            return

        if case.state is CaseState.OUTREACH_ACTIVE:
            self._follow_up(case, summary)
            return

        if case.state is CaseState.DONOR_CONFIRMED:
            self._move(
                case,
                CaseState.COORDINATING,
                "COORDINATION_STARTED",
                {"automated": True},
            )
            summary["coordinating"] += 1
            return

        summary["skipped"] += 1

    def _start_outreach(self, case: CaseRecord) -> bool:
        service = self._outreach_service()
        ranked = rank_donors(case.request, self.repo.list_donors())
        for item in ranked[: max(2, case.request.units * 2)]:
            result = service.prepare(case.id, item.donor.id)
            self._approve_if_enabled(service, result)
        active_case = self._move(
            case,
            CaseState.OUTREACH_ACTIVE,
            "OUTREACH_STARTED",
            {"automated": True},
        )
        if ranked:
            return False

        task = EscalationTask(
            id=str(uuid4()),
            case_id=case.id,
            donor_id="unmatched",
            kind="blood-bank",
            created_at=datetime.fromisoformat(
                self.clock().replace("Z", "+00:00")
            ),
        )
        self.repo.create_task(task)
        self.repo.put_case(
            active_case.model_copy(update={"escalation_level": 2})
        )
        self.repo.append_event(
            case.id,
            "ESCALATION_TASK_CREATED",
            {
                "task_id": task.id,
                "kind": task.kind,
                "reason": "no_compatible_donor",
                "automated": True,
            },
        )
        return True

    def _follow_up(
        self,
        case: CaseRecord,
        summary: dict[str, int],
    ) -> None:
        open_tasks = {
            (task.case_id, task.donor_id)
            for task in self.repo.list_tasks()
            if task.status == "open"
        }
        ranked = rank_donors(case.request, self.repo.list_donors())
        service = self._outreach_service()
        for item in ranked:
            donor_id = item.donor.id
            if (case.id, donor_id) in open_tasks:
                summary["skipped"] += 1
                return
            if case.escalation_level >= len(service.ESCALATION_KINDS):
                summary["skipped"] += 1
                return
            result = service.process_follow_up(case.id, donor_id)
            if result is None:
                continue
            if isinstance(result, EscalationTask):
                summary["escalations"] += 1
            else:
                self._approve_if_enabled(service, result)
                summary["follow_ups"] += 1
            return
        summary["skipped"] += 1

    def _approve_if_enabled(
        self,
        service: OutreachService,
        result,
    ) -> None:
        if (
            isinstance(result, Approval)
            and self.auto_approve
            and result.status == "pending"
        ):
            service.approve(result.id, "carecircle-scheduler@aws")

    def _outreach_service(self) -> OutreachService:
        return OutreachService(
            self.repo,
            self.messenger,
            self.clock,
            mode=self.mode,
        )

    def _move(
        self,
        case: CaseRecord,
        target: CaseState,
        event_type: str,
        payload: dict,
    ) -> CaseRecord:
        next_state = transition(case.state, target)
        updated = case.model_copy(
            update={
                "state": next_state,
                "updated_at": datetime.fromisoformat(
                    self.clock().replace("Z", "+00:00")
                ),
            }
        )
        self.repo.put_case(updated)
        self.repo.append_event(case.id, event_type, payload)
        return updated
