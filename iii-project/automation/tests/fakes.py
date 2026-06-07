from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from app.models import (
    Approval,
    CaseRecord,
    Donor,
    DonorMemory,
    EscalationTask,
    Message,
    MessageAttempt,
)
from app.repositories import IdempotencyConflict


class MemoryRepository:
    def __init__(
        self,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.cases: dict[str, CaseRecord] = {}
        self.donors: dict[str, Donor] = {}
        self.approvals: dict[str, Approval] = {}
        self.message_attempts: list[MessageAttempt] = []
        self.tasks: list[EscalationTask] = []
        self.donor_memory: dict[str, DonorMemory] = {}
        self.idempotency: dict[tuple[str, str], dict[str, str]] = {}
        self.events: list[dict] = []
        self.clock = clock or (
            lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self._create_lock = Lock()
        self._approval_lock = Lock()

    def get_case(self, case_id: str) -> CaseRecord | None:
        return self.cases.get(case_id)

    def list_cases(self) -> list[CaseRecord]:
        return list(self.cases.values())

    def put_case(self, case: CaseRecord) -> None:
        self.cases[case.id] = case

    def find_idempotent_case(
        self, owner_email: str, key: str
    ) -> CaseRecord | None:
        record = self.idempotency.get((owner_email, key))
        return self.get_case(record["case_id"]) if record else None

    def put_idempotency(
        self, owner_email: str, key: str, case_id: str
    ) -> None:
        self.idempotency[(owner_email, key)] = {
            "case_id": case_id,
            "request_hash": "",
        }

    def append_event(
        self, case_id: str, event_type: str, payload: dict
    ) -> None:
        timestamp = self._normalize_timestamp(self.clock())
        event_id = self.id_factory()
        self.events.append(
            {
                "event_id": event_id,
                "case_id": case_id,
                "event_key": f"{timestamp}#{event_id}",
                "type": event_type,
                "timestamp": timestamp,
                "payload": payload,
            }
        )

    def create_case_with_event(
        self,
        case: CaseRecord,
        owner_email: str,
        key: str,
        request_hash: str,
        event: dict,
    ) -> CaseRecord:
        timestamp = self._normalize_timestamp(event["timestamp"])
        event_id = event["event_id"]
        with self._create_lock:
            idempotency_key = (owner_email, key)
            winner = self.idempotency.get(idempotency_key)
            if winner is not None:
                if winner["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "idempotency key was already used for another request"
                    )
                return self.cases[winner["case_id"]]

            self.cases[case.id] = case
            self.idempotency[idempotency_key] = {
                "case_id": case.id,
                "request_hash": request_hash,
            }
            self.events.append(
                {
                    **event,
                    "case_id": case.id,
                    "timestamp": timestamp,
                    "event_key": f"{timestamp}#{event_id}",
                }
            )
            return case

    def get_donor(self, donor_id: str) -> Donor | None:
        return self.donors.get(donor_id)

    def put_donor(self, donor: Donor) -> None:
        self.donors[donor.id] = donor

    def list_donors(self) -> list[Donor]:
        return list(self.donors.values())

    def get_approval(self, approval_id: str) -> Approval | None:
        return self.approvals.get(approval_id)

    def put_approval(self, approval: Approval) -> None:
        self.approvals[approval.id] = approval

    def list_approvals(self) -> list[Approval]:
        return list(self.approvals.values())

    def claim_approval_for_send(
        self, approval_id: str, admin_email: str
    ) -> Approval | None:
        with self._approval_lock:
            approval = self.approvals.get(approval_id)
            if approval is None:
                return None
            if approval.status == "approved":
                return approval
            if approval.status != "pending":
                return None
            claimed = approval.model_copy(
                update={
                    "status": "sending",
                    "decided_by": admin_email,
                    "decided_at": self._normalize_datetime(self.clock()),
                }
            )
            self.approvals[approval_id] = claimed
            return claimed

    def record_attempt(
        self,
        case_id: str,
        donor_id: str,
        channel: str,
        status: str,
        sent_message_id: str | None,
    ) -> MessageAttempt:
        attempt = MessageAttempt(
            case_id=case_id,
            donor_id=donor_id,
            channel=channel,
            status=status,
            sent_message_id=sent_message_id,
            attempted_at=self._normalize_datetime(self.clock()),
        )
        self.message_attempts.append(attempt)
        return attempt

    def count_attempts(self, case_id: str, donor_id: str) -> int:
        return sum(
            1
            for attempt in self.message_attempts
            if attempt.case_id == case_id and attempt.donor_id == donor_id
        )

    def create_task(self, task: EscalationTask) -> EscalationTask:
        self.tasks.append(task)
        return task

    def list_tasks(self) -> list[EscalationTask]:
        return list(self.tasks)

    def put_task(self, task: EscalationTask) -> None:
        self.tasks = [
            task if existing.id == task.id else existing
            for existing in self.tasks
        ]

    def get_donor_memory(self, donor_id: str) -> DonorMemory | None:
        return self.donor_memory.get(donor_id)

    def put_donor_memory(self, memory: DonorMemory) -> None:
        self.donor_memory[memory.donor_id] = memory

    @staticmethod
    def _normalize_timestamp(value: str) -> str:
        return MemoryRepository._normalize_datetime(value).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _normalize_datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return parsed.astimezone(UTC)


class RecordingMessenger:
    def __init__(self) -> None:
        self.sent: list[Message] = []

    def send(self, message: Message) -> str:
        self.sent.append(message)
        return f"recorded-{len(self.sent)}"
