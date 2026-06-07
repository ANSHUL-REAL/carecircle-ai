from datetime import UTC, date, datetime, timedelta
from threading import Barrier, Lock, Thread
from time import sleep

import pytest

from app.messaging import SesMessenger, SimulationMessenger, SnsMessenger
from app.models import (
    BloodRequest,
    CaseRecord,
    CaseState,
    Donor,
    DonorMemory,
    DonorResponse,
)
from app.ranking import rank_donors
from app.services import OutreachService
from tests.fakes import MemoryRepository, RecordingMessenger


def make_request(
    deadline: date | None = None,
) -> BloodRequest:
    return BloodRequest(
        patient_name="Asha",
        blood_group="O-",
        units=1,
        hospital="Doon Hospital",
        city="Dehradun",
        deadline=deadline or date(2026, 6, 9),
        urgency="critical",
    )


def make_case(
    state: CaseState = CaseState.OUTREACH_ACTIVE,
    deadline: date | None = None,
) -> CaseRecord:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    return CaseRecord(
        id="case-1",
        owner_email="patient@example.com",
        request=make_request(deadline),
        state=state,
        created_at=now,
        updated_at=now,
    )


def make_donor(**overrides) -> Donor:
    data = {
        "id": "donor-1",
        "name": "Dev",
        "blood_group": "O-",
        "city": "Dehradun",
        "eligible": True,
        "reliability": 80,
        "fatigue": 10,
        "email": "dev@example.com",
        "phone": "+15555550100",
    }
    data.update(overrides)
    return Donor(**data)


def make_service(
    *,
    mode: str = "real",
    repo: MemoryRepository | None = None,
    messenger: RecordingMessenger | None = None,
    clock=lambda: "2026-06-06T12:00:00Z",
) -> tuple[OutreachService, MemoryRepository, RecordingMessenger]:
    repo = repo or MemoryRepository(clock=clock)
    messenger = messenger or RecordingMessenger()
    service = OutreachService(
        repo=repo,
        messenger=messenger,
        mode=mode,
        clock=clock,
        id_factory=lambda: "approval-1",
    )
    return service, repo, messenger


def seed_case_and_donor(repo: MemoryRepository, donor: Donor | None = None) -> None:
    repo.put_case(make_case())
    repo.put_donor(donor or make_donor())


def test_real_prepare_creates_pending_approval_without_sending() -> None:
    service, repo, messenger = make_service(mode="real")
    seed_case_and_donor(repo)

    approval = service.prepare("case-1", "donor-1")

    assert approval.status == "pending"
    assert repo.get_approval(approval.id) == approval
    assert messenger.sent == []
    assert repo.message_attempts == []


def test_approve_sends_once_and_records_message_sent_event() -> None:
    service, repo, messenger = make_service(mode="real")
    seed_case_and_donor(repo)
    approval = service.prepare("case-1", "donor-1")

    first = service.approve(approval.id, "admin@example.com")
    second = service.approve(approval.id, "admin@example.com")

    assert first.status == "approved"
    assert second.status == "approved"
    assert first.sent_message_id == "recorded-1"
    assert second.sent_message_id == "recorded-1"
    assert len(messenger.sent) == 1
    assert [event["type"] for event in repo.events] == ["MESSAGE_SENT"]


def test_concurrent_approve_claims_and_sends_once() -> None:
    class SlowRecordingMessenger(RecordingMessenger):
        def __init__(self) -> None:
            super().__init__()
            self.lock = Lock()

        def send(self, message):
            sleep(0.05)
            with self.lock:
                return super().send(message)

    service, repo, messenger = make_service(
        mode="real", messenger=SlowRecordingMessenger()
    )
    seed_case_and_donor(repo)
    approval = service.prepare("case-1", "donor-1")
    start = Barrier(3)
    results = []

    def approve() -> None:
        start.wait()
        results.append(service.approve(approval.id, "admin@example.com"))

    threads = [Thread(target=approve), Thread(target=approve)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()

    assert len(messenger.sent) == 1
    assert len(results) == 2
    assert repo.get_approval(approval.id).status == "approved"
    assert repo.get_approval(approval.id).sent_message_id == "recorded-1"


def test_approve_marks_failed_when_messenger_send_raises() -> None:
    class FailingMessenger:
        def send(self, message):
            raise RuntimeError("provider timeout")

    service, repo, _ = make_service(mode="real", messenger=FailingMessenger())
    seed_case_and_donor(repo)
    approval = service.prepare("case-1", "donor-1")

    with pytest.raises(RuntimeError, match="provider timeout"):
        service.approve(approval.id, "admin@example.com")

    failed = repo.get_approval(approval.id)
    assert failed.status == "failed"
    assert failed.decided_by == "admin@example.com"
    assert failed.error_message == "provider timeout"
    assert failed.sent_message_id is None


def test_approve_failed_approval_raises_clear_runtime_error() -> None:
    service, repo, _ = make_service(mode="real")
    seed_case_and_donor(repo)
    approval = service.prepare("case-1", "donor-1")
    repo.put_approval(
        approval.model_copy(
            update={
                "status": "failed",
                "decided_by": "admin@example.com",
                "error_message": "provider timeout",
            }
        )
    )

    with pytest.raises(RuntimeError, match="approval send previously failed"):
        service.approve(approval.id, "admin@example.com")


def test_simulation_prepare_sends_immediately_without_approval() -> None:
    service, repo, messenger = make_service(mode="simulation")
    seed_case_and_donor(repo)

    attempt = service.prepare("case-1", "donor-1")

    assert attempt.status == "sent"
    assert attempt.sent_message_id == "recorded-1"
    assert messenger.sent[0].recipient == "dev@example.com"
    assert repo.approvals == {}
    assert [event["type"] for event in repo.events] == ["MESSAGE_SENT"]


def test_sms_messenger_raises_when_sms_is_disabled(monkeypatch) -> None:
    class SnsClient:
        def publish(self, **kwargs):
            raise AssertionError("publish should not be called")

    monkeypatch.setenv("ENABLE_SMS", "false")

    with pytest.raises(RuntimeError, match="SMS is disabled"):
        SnsMessenger(SnsClient()).send(
            make_service()[0].build_message(make_case(), make_donor(), "sms")
        )


def test_simulation_messenger_returns_sim_prefixed_id() -> None:
    message = make_service()[0].build_message(make_case(), make_donor(), "email")

    message_id = SimulationMessenger().send(message)

    assert message_id.startswith("sim-")


def test_ses_messenger_uses_from_email_and_send_email(monkeypatch) -> None:
    class SesClient:
        def __init__(self) -> None:
            self.requests = []

        def send_email(self, **kwargs):
            self.requests.append(kwargs)
            return {"MessageId": "ses-1"}

    ses = SesClient()
    message = make_service()[0].build_message(make_case(), make_donor(), "email")
    monkeypatch.setenv("SES_FROM_EMAIL", "care@example.com")

    message_id = SesMessenger(ses).send(message)

    assert message_id == "ses-1"
    assert ses.requests == [
        {
            "Source": "care@example.com",
            "Destination": {"ToAddresses": ["dev@example.com"]},
            "Message": {
                "Subject": {"Data": message.subject},
                "Body": {"Text": {"Data": message.body}},
            },
        }
    ]


def test_sms_messenger_publishes_when_sms_enabled(monkeypatch) -> None:
    class SnsClient:
        def __init__(self) -> None:
            self.requests = []

        def publish(self, **kwargs):
            self.requests.append(kwargs)
            return {"MessageId": "sms-1"}

    sns = SnsClient()
    message = make_service()[0].build_message(make_case(), make_donor(), "sms")
    monkeypatch.setenv("ENABLE_SMS", "true")

    message_id = SnsMessenger(sns).send(message)

    assert message_id == "sms-1"
    assert sns.requests == [
        {"PhoneNumber": "+15555550100", "Message": message.body}
    ]


def test_reject_marks_pending_approval_rejected_without_sending() -> None:
    service, repo, messenger = make_service(mode="real")
    seed_case_and_donor(repo)
    approval = service.prepare("case-1", "donor-1")

    rejected = service.reject(approval.id, "admin@example.com")

    assert rejected.status == "rejected"
    assert rejected.decided_by == "admin@example.com"
    assert repo.get_approval(approval.id) == rejected
    assert messenger.sent == []


@pytest.mark.parametrize(
    ("case_state", "donor", "deadline"),
    [
        (CaseState.DONOR_CONFIRMED, make_donor(), date(2026, 6, 9)),
        (CaseState.OUTREACH_ACTIVE, make_donor(opted_out=True), date(2026, 6, 9)),
        (CaseState.CANCELLED, make_donor(), date(2026, 6, 9)),
        (CaseState.OUTREACH_ACTIVE, make_donor(), date(2026, 6, 5)),
    ],
)
def test_follow_up_suppressed_for_accepted_opted_out_closed_or_expired(
    case_state: CaseState, donor: Donor, deadline: date
) -> None:
    service, repo, messenger = make_service(mode="simulation")
    repo.put_case(make_case(state=case_state, deadline=deadline))
    repo.put_donor(donor)

    result = service.process_follow_up("case-1", "donor-1")

    assert result is None
    assert messenger.sent == []
    assert repo.tasks == []


def test_follow_up_retry_limit_advances_escalation_and_creates_task() -> None:
    service, repo, messenger = make_service(mode="simulation")
    seed_case_and_donor(repo)
    repo.record_attempt("case-1", "donor-1", "email", "sent", "old-1")
    repo.record_attempt("case-1", "donor-1", "email", "sent", "old-2")
    repo.record_attempt("case-1", "donor-1", "email", "sent", "old-3")

    task = service.process_follow_up("case-1", "donor-1")

    assert task.kind == "volunteer"
    assert task.case_id == "case-1"
    assert repo.get_case("case-1").escalation_level == 1
    assert messenger.sent == []


def test_opt_out_response_is_permanent_and_suppresses_future_follow_up() -> None:
    service, repo, messenger = make_service(mode="simulation")
    seed_case_and_donor(repo)

    memory = service.record_response(
        "case-1", "donor-1", DonorResponse.OPTED_OUT
    )
    service.process_follow_up("case-1", "donor-1")

    assert memory.opted_out is True
    assert repo.get_donor("donor-1").opted_out is True
    assert messenger.sent == []


def test_completed_donation_updates_future_memory_and_ranking_inputs() -> None:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    service, repo, _ = make_service(mode="simulation")
    seed_case_and_donor(repo)

    memory = service.record_response(
        "case-1",
        "donor-1",
        DonorResponse.COMPLETED_DONATION,
        occurred_at=now,
    )

    assert memory.total_responses == 1
    assert memory.accepted_responses == 1
    assert memory.acceptance_ratio == 1
    assert memory.last_contacted_at == now
    assert memory.next_eligible_at == now + timedelta(days=90)
    assert repo.get_donor("donor-1").eligible is False
    assert repo.get_donor("donor-1").fatigue > 10


def test_completed_donor_is_restored_for_ranking_after_next_eligible_date() -> None:
    donated_at = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    future = donated_at + timedelta(days=91)
    service, repo, _ = make_service(mode="simulation")
    seed_case_and_donor(repo)
    memory = service.record_response(
        "case-1",
        "donor-1",
        DonorResponse.COMPLETED_DONATION,
        occurred_at=donated_at,
    )
    suppressed = repo.get_donor("donor-1")

    current = service.current_donor_for_ranking(suppressed, memory, future)
    ranked = rank_donors(make_request(), [current])

    assert suppressed.eligible is False
    assert current.eligible is True
    assert [item.donor.id for item in ranked] == ["donor-1"]


def test_current_donor_for_ranking_honors_memory_opt_out() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    service, _, _ = make_service(mode="simulation")
    donor = make_donor(opted_out=False, eligible=True)
    memory = DonorMemory(
        donor_id="donor-1",
        opted_out=True,
        next_eligible_at=now - timedelta(days=1),
    )

    current = service.current_donor_for_ranking(donor, memory, now)
    ranked = rank_donors(make_request(), [current])

    assert current.opted_out is True
    assert current.eligible is False
    assert ranked == []
