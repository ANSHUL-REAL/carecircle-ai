from datetime import UTC, date, datetime

from app.models import CaseRecord, CaseState, Donor, EscalationTask
from app.scheduler import AutomationScheduler
from tests.fakes import MemoryRepository, RecordingMessenger


NOW = "2026-06-06T12:00:00Z"


def make_case(
    *,
    state: CaseState = CaseState.DRAFT,
    deadline: date = date(2026, 6, 10),
    escalation_level: int = 0,
) -> CaseRecord:
    return CaseRecord(
        id="case-1",
        owner_email="patient@example.com",
        request={
            "patient_name": "Asha",
            "blood_group": "O-",
            "units": 1,
            "hospital": "Doon Hospital",
            "city": "Dehradun",
            "deadline": deadline,
            "urgency": "critical",
        },
        state=state,
        escalation_level=escalation_level,
        created_at=datetime(2026, 6, 6, 10, tzinfo=UTC),
        updated_at=datetime(2026, 6, 6, 10, tzinfo=UTC),
    )


def make_donor() -> Donor:
    return Donor(
        id="D1",
        name="Dev",
        blood_group="O-",
        city="Dehradun",
        eligible=True,
        reliability=90,
        fatigue=5,
        email="dev@example.com",
    )


def make_scheduler(
    repo: MemoryRepository,
    messenger: RecordingMessenger,
    *,
    mode: str = "simulation",
    auto_approve: bool = True,
) -> AutomationScheduler:
    return AutomationScheduler(
        repo,
        messenger,
        lambda: NOW,
        mode=mode,
        auto_approve=auto_approve,
        max_cases=25,
    )


def test_cycle_plans_draft_and_starts_initial_outreach() -> None:
    repo = MemoryRepository(clock=lambda: NOW)
    repo.put_case(make_case())
    repo.put_donor(make_donor())
    messenger = RecordingMessenger()

    summary = make_scheduler(repo, messenger).run()

    assert repo.get_case("case-1").state is CaseState.OUTREACH_ACTIVE
    assert len(messenger.sent) == 1
    assert summary == {
        "processed": 1,
        "planned": 1,
        "outreach_started": 1,
        "follow_ups": 0,
        "escalations": 0,
        "coordinating": 0,
        "expired": 0,
        "skipped": 0,
    }


def test_cycle_auto_approves_email_outreach_when_enabled() -> None:
    repo = MemoryRepository(clock=lambda: NOW)
    repo.put_case(make_case())
    repo.put_donor(make_donor())
    messenger = RecordingMessenger()

    make_scheduler(repo, messenger, mode="email").run()

    approval = next(iter(repo.approvals.values()))
    assert approval.status == "approved"
    assert approval.sent_message_id == "recorded-1"
    assert len(messenger.sent) == 1


def test_cycle_creates_blood_bank_task_when_no_donor_matches() -> None:
    repo = MemoryRepository(clock=lambda: NOW)
    repo.put_case(make_case())

    summary = make_scheduler(repo, RecordingMessenger()).run()

    assert repo.get_case("case-1").state is CaseState.OUTREACH_ACTIVE
    assert len(repo.tasks) == 1
    assert repo.tasks[0].kind == "blood-bank"
    assert repo.tasks[0].donor_id == "unmatched"
    assert summary["escalations"] == 1


def test_cycle_follows_up_active_case_once_per_run() -> None:
    repo = MemoryRepository(clock=lambda: NOW)
    repo.put_case(make_case(state=CaseState.OUTREACH_ACTIVE))
    repo.put_donor(make_donor())
    repo.record_attempt("case-1", "D1", "email", "sent", "old-1")
    messenger = RecordingMessenger()

    summary = make_scheduler(repo, messenger).run()

    assert repo.count_attempts("case-1", "D1") == 2
    assert summary["follow_ups"] == 1


def test_cycle_does_not_duplicate_open_escalation_task() -> None:
    repo = MemoryRepository(clock=lambda: NOW)
    repo.put_case(
        make_case(
            state=CaseState.OUTREACH_ACTIVE,
            escalation_level=1,
        )
    )
    repo.put_donor(make_donor())
    for index in range(3):
        repo.record_attempt(
            "case-1",
            "D1",
            "email",
            "sent",
            f"old-{index}",
        )
    repo.create_task(
        EscalationTask(
            id="task-1",
            case_id="case-1",
            donor_id="D1",
            kind="volunteer",
            created_at=datetime(2026, 6, 6, 11, tzinfo=UTC),
        )
    )

    summary = make_scheduler(repo, RecordingMessenger()).run()

    assert len(repo.tasks) == 1
    assert summary["skipped"] == 1


def test_cycle_moves_confirmed_case_to_coordination() -> None:
    repo = MemoryRepository(clock=lambda: NOW)
    repo.put_case(make_case(state=CaseState.DONOR_CONFIRMED))

    summary = make_scheduler(repo, RecordingMessenger()).run()

    assert repo.get_case("case-1").state is CaseState.COORDINATING
    assert summary["coordinating"] == 1


def test_cycle_expires_overdue_active_case() -> None:
    repo = MemoryRepository(clock=lambda: NOW)
    repo.put_case(
        make_case(
            state=CaseState.OUTREACH_ACTIVE,
            deadline=date(2026, 6, 5),
        )
    )

    summary = make_scheduler(repo, RecordingMessenger()).run()

    assert repo.get_case("case-1").state is CaseState.EXPIRED
    assert summary["expired"] == 1
