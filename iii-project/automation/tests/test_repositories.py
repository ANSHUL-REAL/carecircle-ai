from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from pydantic import BaseModel

from app.models import (
    Approval,
    BloodRequest,
    CaseRecord,
    CaseState,
    Donor,
    DonorMemory,
    EscalationTask,
    Message,
)
from app.repositories import DynamoRepository, IdempotencyConflict


def make_client():
    return boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def make_case() -> CaseRecord:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    return CaseRecord(
        id="case-1",
        owner_email="patient@example.com",
        request=BloodRequest(
            patient_name="Asha",
            blood_group="O-",
            units=1,
            hospital="Doon Hospital",
            city="Dehradun",
            deadline=date(2026, 6, 9),
            urgency="critical",
        ),
        state=CaseState.DRAFT,
        created_at=now,
        updated_at=now,
    )


def make_donor() -> Donor:
    return Donor(
        id="donor-1",
        name="Dev",
        blood_group="O-",
        city="Dehradun",
        eligible=True,
        reliability=80,
        fatigue=10,
        email="dev@example.com",
        phone="+15555550100",
    )


def make_message() -> Message:
    return Message(
        case_id="case-1",
        donor_id="donor-1",
        channel="email",
        recipient="dev@example.com",
        subject="CareCircle request",
        body="Can you donate today?",
    )


def make_approval() -> Approval:
    return Approval(
        id="approval-1",
        case_id="case-1",
        donor_id="donor-1",
        channel="email",
        message=make_message(),
        requested_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
    )


def make_repository(client):
    return DynamoRepository(
        client=client,
        cases_table="CareCircleCases",
        events_table="CareCircleEvents",
        donors_table="CareCircleDonors",
        outreach_table="CareCircleOutreach",
        approvals_table="CareCircleApprovals",
        tasks_table="CareCircleTasks",
        clock=lambda: "2026-06-06T12:00:00Z",
        id_factory=lambda: "event-1",
    )


def test_put_case_serializes_case_for_low_level_client() -> None:
    client = make_client()
    repo = make_repository(client)
    case = make_case()
    expected_item = {
        "id": {"S": "case-1"},
        "owner_email": {"S": "patient@example.com"},
        "request": {
            "M": {
                "patient_name": {"S": "Asha"},
                "blood_group": {"S": "O-"},
                "units": {"N": "1"},
                "hospital": {"S": "Doon Hospital"},
                "city": {"S": "Dehradun"},
                "deadline": {"S": "2026-06-09"},
                "urgency": {"S": "critical"},
                "component": {"S": "red_cells"},
                "diagnosis": {"NULL": True},
            }
        },
        "state": {"S": "DRAFT"},
        "escalation_level": {"N": "0"},
        "created_at": {"S": "2026-06-06T12:00:00Z"},
        "updated_at": {"S": "2026-06-06T12:00:00Z"},
    }

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {"TableName": "CareCircleCases", "Item": expected_item},
        )
        repo.put_case(case)


def test_get_case_deserializes_case_record() -> None:
    client = make_client()
    repo = make_repository(client)
    case = make_case()
    item = {
        key: repo.serializer.serialize(value)
        for key, value in case.model_dump(mode="json").items()
    }

    with Stubber(client) as stubber:
        stubber.add_response(
            "get_item",
            {"Item": item},
            {
                "TableName": "CareCircleCases",
                "Key": {"id": {"S": "case-1"}},
                "ConsistentRead": True,
            },
        )
        loaded = repo.get_case("case-1")

    assert loaded == case


def test_put_and_get_donor_use_donors_table() -> None:
    client = make_client()
    repo = make_repository(client)
    donor = make_donor()
    item = repo._serialize_item(donor.model_dump(mode="json"))

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {"TableName": "CareCircleDonors", "Item": item},
        )
        repo.put_donor(donor)
        stubber.add_response(
            "get_item",
            {"Item": item},
            {
                "TableName": "CareCircleDonors",
                "Key": {"id": {"S": "donor-1"}},
                "ConsistentRead": True,
            },
        )
        loaded = repo.get_donor("donor-1")

    assert loaded == donor


def test_put_and_get_approval_use_approvals_table() -> None:
    client = make_client()
    repo = make_repository(client)
    approval = make_approval()
    item = repo._serialize_item(approval.model_dump(mode="json"))

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {"TableName": "CareCircleApprovals", "Item": item},
        )
        repo.put_approval(approval)
        stubber.add_response(
            "get_item",
            {"Item": item},
            {
                "TableName": "CareCircleApprovals",
                "Key": {"id": {"S": "approval-1"}},
                "ConsistentRead": True,
            },
        )
        loaded = repo.get_approval("approval-1")

    assert loaded == approval


def test_claim_approval_for_send_conditionally_moves_pending_to_sending() -> None:
    client = make_client()
    repo = make_repository(client)
    approval = make_approval().model_copy(
        update={
            "status": "sending",
            "decided_by": "admin@example.com",
            "decided_at": datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        }
    )
    item = repo._serialize_item(approval.model_dump(mode="json"))

    with Stubber(client) as stubber:
        stubber.add_response(
            "update_item",
            {"Attributes": item},
            {
                "TableName": "CareCircleApprovals",
                "Key": {"id": {"S": "approval-1"}},
                "UpdateExpression": (
                    "SET #status = :sending, decided_by = :admin_email, "
                    "decided_at = :decided_at"
                ),
                "ConditionExpression": "#status = :pending",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":sending": {"S": "sending"},
                    ":pending": {"S": "pending"},
                    ":admin_email": {"S": "admin@example.com"},
                    ":decided_at": {"S": "2026-06-06T12:00:00Z"},
                },
                "ReturnValues": "ALL_NEW",
            },
        )
        claimed = repo.claim_approval_for_send(
            "approval-1", "admin@example.com"
        )

    assert claimed == approval


def test_record_and_count_message_attempts_use_outreach_table() -> None:
    client = make_client()
    repo = make_repository(client)
    expected_item = {
        "id": {"S": "event-1"},
        "case_id": {"S": "case-1"},
        "attempt_key": {"S": "donor-1#2026-06-06T12:00:00Z#event-1"},
        "donor_id": {"S": "donor-1"},
        "channel": {"S": "email"},
        "status": {"S": "sent"},
        "sent_message_id": {"S": "message-1"},
        "attempted_at": {"S": "2026-06-06T12:00:00Z"},
    }

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {"TableName": "CareCircleOutreach", "Item": expected_item},
        )
        attempt = repo.record_attempt(
            "case-1", "donor-1", "email", "sent", "message-1"
        )
        stubber.add_response(
            "query",
            {"Count": 2},
            {
                "TableName": "CareCircleOutreach",
                "KeyConditionExpression": (
                    "case_id = :case_id AND begins_with("
                    "attempt_key, :attempt_prefix)"
                ),
                "ExpressionAttributeValues": {
                    ":case_id": {"S": "case-1"},
                    ":attempt_prefix": {"S": "donor-1#"},
                },
                "Select": "COUNT",
                "ConsistentRead": True,
            },
        )
        count = repo.count_attempts("case-1", "donor-1")

    assert attempt.sent_message_id == "message-1"
    assert count == 2


def test_create_task_uses_tasks_table() -> None:
    client = make_client()
    repo = make_repository(client)
    task = EscalationTask(
        id="task-1",
        case_id="case-1",
        donor_id="donor-1",
        kind="volunteer",
        created_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
    )
    item = repo._serialize_item(task.model_dump(mode="json"))

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {"TableName": "CareCircleTasks", "Item": item},
        )
        created = repo.create_task(task)

    assert created == task


def test_put_and_get_donor_memory_use_prefixed_donor_record() -> None:
    client = make_client()
    repo = make_repository(client)
    memory = DonorMemory(
        donor_id="donor-1",
        total_responses=2,
        accepted_responses=1,
        last_contacted_at=datetime(2026, 6, 6, 12, 0, tzinfo=UTC),
        fatigue=30,
    )
    item = repo._serialize_item(
        {"id": "MEMORY#donor-1", **memory.model_dump(mode="json")}
    )

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {"TableName": "CareCircleDonors", "Item": item},
        )
        repo.put_donor_memory(memory)
        stubber.add_response(
            "get_item",
            {"Item": item},
            {
                "TableName": "CareCircleDonors",
                "Key": {"id": {"S": "MEMORY#donor-1"}},
                "ConsistentRead": True,
            },
        )
        loaded = repo.get_donor_memory("donor-1")

    assert loaded == memory


def test_idempotency_uses_prefixed_conditional_record_and_resolves_case() -> None:
    client = make_client()
    repo = make_repository(client)
    idempotency_id = (
        "IDEMPOTENCY#patient@example.com#request-1"
    )
    case = make_case()
    case_item = {
        key: repo.serializer.serialize(value)
        for key, value in case.model_dump(mode="json").items()
    }

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {
                "TableName": "CareCircleCases",
                "Item": {
                    "id": {"S": idempotency_id},
                    "record_type": {"S": "IDEMPOTENCY"},
                    "owner_email": {"S": "patient@example.com"},
                    "idempotency_key": {"S": "request-1"},
                    "case_id": {"S": "case-1"},
                },
                "ConditionExpression": "attribute_not_exists(id)",
            },
        )
        repo.put_idempotency(
            "patient@example.com", "request-1", "case-1"
        )
        stubber.add_response(
            "get_item",
            {"Item": {"case_id": {"S": "case-1"}}},
            {
                "TableName": "CareCircleCases",
                "Key": {"id": {"S": idempotency_id}},
                "ConsistentRead": True,
            },
        )
        stubber.add_response(
            "get_item",
            {"Item": case_item},
            {
                "TableName": "CareCircleCases",
                "Key": {"id": {"S": "case-1"}},
                "ConsistentRead": True,
            },
        )
        loaded = repo.find_idempotent_case(
            "patient@example.com", "request-1"
        )

    assert loaded == case


def test_list_cases_ignores_idempotency_records() -> None:
    client = make_client()
    repo = make_repository(client)
    case = make_case()
    case_item = repo._serialize_item(case)
    idempotency_item = repo._serialize_item(
        {
            "id": "IDEMPOTENCY#patient@example.com#request-1",
            "record_type": "IDEMPOTENCY",
            "owner_email": "patient@example.com",
            "idempotency_key": "request-1",
            "case_id": case.id,
        }
    )

    with Stubber(client) as stubber:
        stubber.add_response(
            "scan",
            {"Items": [idempotency_item, case_item]},
            {"TableName": "CareCircleCases"},
        )
        cases = repo.list_cases()

    assert cases == [case]


def test_append_event_includes_event_id_timestamp_and_case_id() -> None:
    client = make_client()
    repo = make_repository(client)

    with Stubber(client) as stubber:
        stubber.add_response(
            "put_item",
            {},
            {
                "TableName": "CareCircleEvents",
                "Item": {
                    "event_id": {"S": "event-1"},
                    "case_id": {"S": "case-1"},
                    "event_key": {
                        "S": "2026-06-06T12:00:00Z#event-1"
                    },
                    "type": {"S": "CASE_CREATED"},
                    "timestamp": {"S": "2026-06-06T12:00:00Z"},
                    "payload": {
                        "M": {
                            "owner": {"S": "patient@example.com"}
                        }
                    },
                },
            },
        )
        repo.append_event(
            "case-1",
            "CASE_CREATED",
            {"owner": "patient@example.com"},
        )


def test_create_case_with_event_uses_one_transaction() -> None:
    client = make_client()
    repo = make_repository(client)
    case = make_case()
    request_hash = "request-hash"
    event = {
        "event_id": "event-1",
        "timestamp": "2026-06-06T12:00:00Z",
        "type": "CASE_CREATED",
        "payload": {"owner": "patient@example.com"},
    }
    expected_case = repo._serialize_item(case.model_dump(mode="json"))
    expected_idempotency = repo._serialize_item(
        {
            "id": "IDEMPOTENCY#patient@example.com#request-1",
            "record_type": "IDEMPOTENCY",
            "owner_email": "patient@example.com",
            "idempotency_key": "request-1",
            "case_id": "case-1",
            "request_hash": request_hash,
        }
    )
    expected_event = repo._serialize_item(
        {
            **event,
            "case_id": "case-1",
            "event_key": "2026-06-06T12:00:00Z#event-1",
        }
    )

    with Stubber(client) as stubber:
        stubber.add_response(
            "transact_write_items",
            {},
            {
                "TransactItems": [
                    {
                        "Put": {
                            "TableName": "CareCircleCases",
                            "Item": expected_case,
                            "ConditionExpression": "attribute_not_exists(id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": "CareCircleCases",
                            "Item": expected_idempotency,
                            "ConditionExpression": "attribute_not_exists(id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": "CareCircleEvents",
                            "Item": expected_event,
                            "ConditionExpression": (
                                "attribute_not_exists(case_id) AND "
                                "attribute_not_exists(event_key)"
                            ),
                        }
                    },
                ]
            },
        )
        winner = repo.create_case_with_event(
            case,
            "patient@example.com",
            "request-1",
            request_hash,
            event,
        )

    assert winner == case


def test_transaction_conflict_returns_same_request_winner() -> None:
    client = make_client()
    repo = make_repository(client)
    case = make_case()
    request_hash = "request-hash"
    event = {
        "event_id": "event-1",
        "case_id": "case-1",
        "timestamp": "2026-06-06T12:00:00Z",
        "type": "CASE_CREATED",
        "payload": {},
    }
    winner = case.model_copy(update={"id": "case-winner"})
    winner_item = repo._serialize_item(winner.model_dump(mode="json"))

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "transact_write_items",
            service_error_code="TransactionCanceledException",
            expected_params=repo._create_transaction(
                case,
                "patient@example.com",
                "request-1",
                request_hash,
                event,
            ),
        )
        stubber.add_response(
            "get_item",
            {
                "Item": {
                    "case_id": {"S": "case-winner"},
                    "request_hash": {"S": request_hash},
                }
            },
            {
                "TableName": "CareCircleCases",
                "Key": {
                    "id": {
                        "S": (
                            "IDEMPOTENCY#patient@example.com#request-1"
                        )
                    }
                },
                "ConsistentRead": True,
            },
        )
        stubber.add_response(
            "get_item",
            {"Item": winner_item},
            {
                "TableName": "CareCircleCases",
                "Key": {"id": {"S": "case-winner"}},
                "ConsistentRead": True,
            },
        )
        loaded = repo.create_case_with_event(
            case,
            "patient@example.com",
            "request-1",
            request_hash,
            event,
        )

    assert loaded == winner


def test_transaction_conflict_rejects_different_request_hash() -> None:
    client = make_client()
    repo = make_repository(client)
    case = make_case()
    event = {
        "event_id": "event-1",
        "case_id": "case-1",
        "timestamp": "2026-06-06T12:00:00Z",
        "type": "CASE_CREATED",
        "payload": {},
    }

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "transact_write_items",
            service_error_code="TransactionCanceledException",
            expected_params=repo._create_transaction(
                case,
                "patient@example.com",
                "request-1",
                "new-hash",
                event,
            ),
        )
        stubber.add_response(
            "get_item",
            {
                "Item": {
                    "case_id": {"S": "case-winner"},
                    "request_hash": {"S": "old-hash"},
                }
            },
            {
                "TableName": "CareCircleCases",
                "Key": {
                    "id": {
                        "S": (
                            "IDEMPOTENCY#patient@example.com#request-1"
                        )
                    }
                },
                "ConsistentRead": True,
            },
        )
        with pytest.raises(IdempotencyConflict):
            repo.create_case_with_event(
                case,
                "patient@example.com",
                "request-1",
                "new-hash",
                event,
            )


def test_nonconditional_transaction_cancellation_is_not_swallowed() -> None:
    class FailingClient:
        def transact_write_items(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "TransactionCanceledException",
                        "Message": "transaction conflict",
                    },
                    "CancellationReasons": [
                        {"Code": "TransactionConflict"}
                    ],
                },
                "TransactWriteItems",
            )

    repo = make_repository(FailingClient())
    case = make_case()
    event = {
        "event_id": "event-1",
        "timestamp": "2026-06-06T12:00:00Z",
        "type": "CASE_CREATED",
        "payload": {},
    }

    with pytest.raises(ClientError) as raised:
        repo.create_case_with_event(
            case,
            "patient@example.com",
            "request-1",
            "request-hash",
            event,
        )

    assert (
        raised.value.response["CancellationReasons"][0]["Code"]
        == "TransactionConflict"
    )


class PayloadState(StrEnum):
    READY = "ready"


class PayloadModel(BaseModel):
    score: float


def test_recursive_serialization_normalizes_supported_payload_values() -> None:
    repo = make_repository(make_client())
    value = {
        "at": datetime(2026, 6, 6, 17, 30, tzinfo=UTC),
        "score": 1.25,
        "state": PayloadState.READY,
        "model": PayloadModel(score=2.5),
        "items": [3.75],
    }

    normalized = repo._normalize(value)

    assert normalized == {
        "at": "2026-06-06T17:30:00Z",
        "score": Decimal("1.25"),
        "state": "ready",
        "model": {"score": Decimal("2.5")},
        "items": [Decimal("3.75")],
    }


def test_append_event_rejects_naive_timestamp() -> None:
    repo = make_repository(make_client())
    repo.clock = lambda: "2026-06-06T12:00:00"

    with pytest.raises(ValueError, match="timezone-aware"):
        repo.append_event("case-1", "CASE_CREATED", {})


def test_dynamo_client_errors_are_not_swallowed() -> None:
    client = make_client()
    repo = make_repository(client)

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "get_item",
            service_error_code="ProvisionedThroughputExceededException",
            expected_params={
                "TableName": "CareCircleCases",
                "Key": {"id": {"S": "case-1"}},
                "ConsistentRead": True,
            },
        )
        with pytest.raises(ClientError):
            repo.get_case("case-1")
