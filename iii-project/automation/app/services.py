from collections.abc import Callable
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.messaging import Messenger
from app.models import (
    Approval,
    BloodRequest,
    CaseRecord,
    CaseState,
    Donor,
    DonorMemory,
    DonorResponse,
    EscalationTask,
    Message,
    MessageAttempt,
)
from app.repositories import CaseRepository


class CaseService:
    def __init__(
        self,
        repo: CaseRepository,
        clock: Callable[[], str],
        id_factory: Callable[[], str] | None = None,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repo = repo
        self.clock = clock
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.event_id_factory = event_id_factory or (
            lambda: str(uuid4())
        )

    def create_case(
        self,
        owner_email: str,
        request: BloodRequest,
        idempotency_key: str,
    ) -> CaseRecord:
        now = datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware ISO timestamp")
        now = now.astimezone(UTC)

        case = CaseRecord(
            id=self.id_factory(),
            owner_email=owner_email,
            request=request,
            state=CaseState.DRAFT,
            created_at=now,
            updated_at=now,
        )
        timestamp = now.isoformat().replace("+00:00", "Z")
        event = {
            "event_id": self.event_id_factory(),
            "case_id": case.id,
            "type": "CASE_CREATED",
            "timestamp": timestamp,
            "payload": {"owner": owner_email},
        }
        return self.repo.create_case_with_event(
            case,
            owner_email,
            idempotency_key,
            self.request_hash(request),
            event,
        )

    @staticmethod
    def request_hash(request: BloodRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class OutreachService:
    """Coordinates outreach; callers must pass an admin-authenticated principal."""

    RETRY_LIMIT = 3
    ESCALATION_KINDS = ("volunteer", "blood-bank", "Blood Warrior")

    def __init__(
        self,
        repo: CaseRepository,
        messenger: Messenger,
        clock: Callable[[], str],
        *,
        mode: str = "simulation",
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repo = repo
        self.messenger = messenger
        self.clock = clock
        self.mode = mode
        self.id_factory = id_factory or (lambda: str(uuid4()))

    def prepare(
        self,
        case_id: str,
        donor_id: str,
        channel: str = "email",
    ) -> Approval | MessageAttempt:
        case = self._require_case(case_id)
        donor = self._require_donor(donor_id)
        message = self.build_message(case, donor, channel)
        if self.mode == "simulation":
            sent_message_id = self.messenger.send(message)
            attempt = self.repo.record_attempt(
                case_id, donor_id, channel, "sent", sent_message_id
            )
            self.repo.append_event(
                case_id,
                "MESSAGE_SENT",
                {
                    "donor_id": donor_id,
                    "channel": channel,
                    "message_id": sent_message_id,
                    "simulation": True,
                },
            )
            return attempt

        approval = Approval(
            id=self.id_factory(),
            case_id=case_id,
            donor_id=donor_id,
            channel=channel,
            message=message,
            requested_at=self._now(),
        )
        self.repo.put_approval(approval)
        return approval

    def approve(self, approval_id: str, admin_email: str) -> Approval:
        approval = self.repo.claim_approval_for_send(approval_id, admin_email)
        if approval is None:
            existing = self._require_approval(approval_id)
            if existing.status == "rejected":
                raise ValueError("approval is rejected")
            if existing.status == "failed":
                raise RuntimeError(
                    "approval send previously failed"
                    + (
                        f": {existing.error_message}"
                        if existing.error_message
                        else ""
                    )
                )
            return existing
        if approval.status == "approved":
            return approval
        if approval.status == "rejected":
            raise ValueError("approval is rejected")
        if approval.sent_message_id is not None:
            return approval
        if approval.status == "failed":
            raise RuntimeError(
                "approval send previously failed"
                + (
                    f": {approval.error_message}"
                    if approval.error_message
                    else ""
                )
            )
        if approval.status != "sending":
            raise ValueError("approval must be claimed for sending")

        try:
            sent_message_id = self.messenger.send(approval.message)
        except Exception as error:
            failed = approval.model_copy(
                update={
                    "status": "failed",
                    "decided_at": self._now(),
                    "decided_by": admin_email,
                    "error_message": str(error),
                }
            )
            self.repo.put_approval(failed)
            raise
        approved = approval.model_copy(
            update={
                "status": "approved",
                "decided_at": self._now(),
                "decided_by": admin_email,
                "sent_message_id": sent_message_id,
                "error_message": None,
            }
        )
        self.repo.put_approval(approved)
        self.repo.record_attempt(
            approved.case_id,
            approved.donor_id,
            approved.channel,
            "sent",
            sent_message_id,
        )
        self.repo.append_event(
            approved.case_id,
            "MESSAGE_SENT",
            {
                "donor_id": approved.donor_id,
                "channel": approved.channel,
                "message_id": sent_message_id,
                "approved_by": admin_email,
            },
        )
        return approved

    def reject(self, approval_id: str, admin_email: str) -> Approval:
        approval = self._require_approval(approval_id)
        if approval.status != "pending":
            raise ValueError("approval must be pending")
        rejected = approval.model_copy(
            update={
                "status": "rejected",
                "decided_at": self._now(),
                "decided_by": admin_email,
            }
        )
        self.repo.put_approval(rejected)
        return rejected

    def process_follow_up(
        self,
        case_id: str,
        donor_id: str,
        channel: str = "email",
    ) -> MessageAttempt | EscalationTask | None:
        case = self._require_case(case_id)
        donor = self._require_donor(donor_id)
        if self._should_skip_follow_up(case, donor):
            return None
        if self.repo.count_attempts(case_id, donor_id) >= self.RETRY_LIMIT:
            return self._escalate(case, donor_id)
        return self.prepare(case_id, donor_id, channel)

    def record_response(
        self,
        case_id: str,
        donor_id: str,
        response: DonorResponse,
        *,
        occurred_at: datetime | None = None,
    ) -> DonorMemory:
        self._require_case(case_id)
        donor = self._require_donor(donor_id)
        occurred_at = occurred_at or self._now()
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")

        current = self.repo.get_donor_memory(donor_id) or DonorMemory(
            donor_id=donor_id,
            fatigue=donor.fatigue,
        )
        updated = current.with_response(response, occurred_at)
        self.repo.put_donor_memory(updated)

        donor_update = {"fatigue": updated.fatigue}
        if updated.opted_out:
            donor_update["opted_out"] = True
        if response is DonorResponse.COMPLETED_DONATION:
            donor_update["eligible"] = False
        self.repo.put_donor(donor.model_copy(update=donor_update))
        return updated

    def current_donor_for_ranking(
        self,
        donor: Donor,
        memory: DonorMemory | None,
        now: datetime,
    ) -> Donor:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if memory is None:
            return donor
        if memory.opted_out:
            return donor.model_copy(
                update={"opted_out": True, "eligible": False}
            )
        if memory.next_eligible_at is None or memory.next_eligible_at > now:
            return donor
        return donor.model_copy(update={"eligible": True})

    def build_message(
        self,
        case: CaseRecord,
        donor: Donor,
        channel: str,
    ) -> Message:
        recipient = donor.phone if channel == "sms" else donor.email
        if not recipient:
            raise ValueError(f"donor has no {channel} recipient")
        subject = f"CareCircle blood request for {case.request.blood_group}"
        body = (
            f"Hi {donor.name}, {case.request.patient_name} needs "
            f"{case.request.units} unit(s) of {case.request.blood_group} "
            f"blood at {case.request.hospital} in {case.request.city}."
        )
        return Message(
            case_id=case.id,
            donor_id=donor.id,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
        )

    def _escalate(self, case: CaseRecord, donor_id: str) -> EscalationTask:
        new_level = case.escalation_level + 1
        kind_index = min(new_level - 1, len(self.ESCALATION_KINDS) - 1)
        task = EscalationTask(
            id=self.id_factory(),
            case_id=case.id,
            donor_id=donor_id,
            kind=self.ESCALATION_KINDS[kind_index],
            created_at=self._now(),
        )
        self.repo.put_case(case.model_copy(update={"escalation_level": new_level}))
        return self.repo.create_task(task)

    def _should_skip_follow_up(self, case: CaseRecord, donor: Donor) -> bool:
        if donor.opted_out:
            return True
        if case.state in {
            CaseState.DONOR_CONFIRMED,
            CaseState.COORDINATING,
            CaseState.FULFILLED,
            CaseState.CANCELLED,
            CaseState.EXPIRED,
            CaseState.UNFULFILLED,
        }:
            return True
        return case.request.deadline < self._now().date()

    def _require_case(self, case_id: str) -> CaseRecord:
        case = self.repo.get_case(case_id)
        if case is None:
            raise ValueError("case not found")
        return case

    def _require_donor(self, donor_id: str) -> Donor:
        donor = self.repo.get_donor(donor_id)
        if donor is None:
            raise ValueError("donor not found")
        return donor

    def _require_approval(self, approval_id: str) -> Approval:
        approval = self.repo.get_approval(approval_id)
        if approval is None:
            raise ValueError("approval not found")
        return approval

    def _now(self) -> datetime:
        parsed = datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware ISO timestamp")
        return parsed.astimezone(UTC)
