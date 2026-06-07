from datetime import date

from app.models import BloodRequest, CaseState
import pytest

from app.repositories import IdempotencyConflict
from app.services import CaseService
from tests.fakes import MemoryRepository


def make_request() -> BloodRequest:
    return BloodRequest(
        patient_name="Asha",
        blood_group="O-",
        units=1,
        hospital="Doon Hospital",
        city="Dehradun",
        deadline=date(2026, 6, 9),
        urgency="critical",
    )


def test_create_case_persists_draft_case_idempotency_and_audit_event() -> None:
    repo = MemoryRepository()
    service = CaseService(
        repo=repo,
        clock=lambda: "2026-06-06T12:00:00Z",
        id_factory=lambda: "case-1",
        event_id_factory=lambda: "event-1",
    )

    case = service.create_case(
        owner_email="patient@example.com",
        request=make_request(),
        idempotency_key="request-1",
    )

    assert case.id == "case-1"
    assert case.state == CaseState.DRAFT
    assert case.created_at.isoformat() == "2026-06-06T12:00:00+00:00"
    assert case.updated_at == case.created_at
    assert repo.cases == {"case-1": case}
    assert repo.idempotency == {
        ("patient@example.com", "request-1"): {
            "case_id": "case-1",
            "request_hash": service.request_hash(make_request()),
        }
    }
    assert repo.events == [
        {
            "event_id": "event-1",
            "case_id": "case-1",
            "event_key": "2026-06-06T12:00:00Z#event-1",
            "type": "CASE_CREATED",
            "timestamp": "2026-06-06T12:00:00Z",
            "payload": {"owner": "patient@example.com"},
        }
    ]


def test_create_case_returns_idempotent_case_without_duplicate_writes() -> None:
    repo = MemoryRepository()
    generated_ids = iter(["case-1", "case-2"])
    service = CaseService(
        repo=repo,
        clock=lambda: "2026-06-06T12:00:00Z",
        id_factory=lambda: next(generated_ids),
        event_id_factory=lambda: "event-1",
    )

    first = service.create_case(
        "patient@example.com", make_request(), "request-1"
    )
    second = service.create_case(
        "patient@example.com", make_request(), "request-1"
    )

    assert second is first
    assert list(repo.cases) == ["case-1"]
    assert len(repo.events) == 1


def test_create_case_rejects_same_key_for_different_request() -> None:
    repo = MemoryRepository()
    service = CaseService(
        repo=repo,
        clock=lambda: "2026-06-06T12:00:00Z",
        id_factory=lambda: "case-1",
        event_id_factory=lambda: "event-1",
    )
    service.create_case(
        "patient@example.com", make_request(), "request-1"
    )
    changed_request = make_request().model_copy(update={"units": 2})

    with pytest.raises(IdempotencyConflict):
        service.create_case(
            "patient@example.com", changed_request, "request-1"
        )


def test_create_case_rejects_naive_clock_timestamp() -> None:
    service = CaseService(
        repo=MemoryRepository(),
        clock=lambda: "2026-06-06T12:00:00",
        id_factory=lambda: "case-1",
        event_id_factory=lambda: "event-1",
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        service.create_case(
            "patient@example.com", make_request(), "request-1"
        )


def test_create_case_normalizes_aware_clock_to_utc() -> None:
    repo = MemoryRepository()
    service = CaseService(
        repo=repo,
        clock=lambda: "2026-06-06T17:30:00+05:30",
        id_factory=lambda: "case-1",
        event_id_factory=lambda: "event-1",
    )

    case = service.create_case(
        "patient@example.com", make_request(), "request-1"
    )

    assert case.created_at.isoformat() == "2026-06-06T12:00:00+00:00"
    assert repo.events[0]["timestamp"] == "2026-06-06T12:00:00Z"
    assert repo.events[0]["event_key"] == (
        "2026-06-06T12:00:00Z#event-1"
    )
