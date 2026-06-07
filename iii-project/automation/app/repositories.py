import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol
from uuid import uuid4

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from pydantic import BaseModel

from app.models import (
    Approval,
    CaseRecord,
    Donor,
    DonorMemory,
    EscalationTask,
    MessageAttempt,
)


class IdempotencyConflict(Exception):
    pass


class CaseRepository(Protocol):
    def get_case(self, case_id: str) -> CaseRecord | None: ...

    def list_cases(self) -> list[CaseRecord]: ...

    def put_case(self, case: CaseRecord) -> None: ...

    def find_idempotent_case(
        self, owner_email: str, key: str
    ) -> CaseRecord | None: ...

    def put_idempotency(
        self, owner_email: str, key: str, case_id: str
    ) -> None: ...

    def append_event(
        self, case_id: str, event_type: str, payload: dict
    ) -> None: ...

    def create_case_with_event(
        self,
        case: CaseRecord,
        owner_email: str,
        key: str,
        request_hash: str,
        event: dict,
    ) -> CaseRecord: ...

    def get_donor(self, donor_id: str) -> Donor | None: ...

    def put_donor(self, donor: Donor) -> None: ...

    def list_donors(self) -> list[Donor]: ...

    def get_approval(self, approval_id: str) -> Approval | None: ...

    def put_approval(self, approval: Approval) -> None: ...

    def list_approvals(self) -> list[Approval]: ...

    def claim_approval_for_send(
        self, approval_id: str, admin_email: str
    ) -> Approval | None: ...

    def record_attempt(
        self,
        case_id: str,
        donor_id: str,
        channel: str,
        status: str,
        sent_message_id: str | None,
    ) -> MessageAttempt: ...

    def count_attempts(self, case_id: str, donor_id: str) -> int: ...

    def create_task(self, task: EscalationTask) -> EscalationTask: ...

    def list_tasks(self) -> list[EscalationTask]: ...

    def put_task(self, task: EscalationTask) -> None: ...

    def get_donor_memory(self, donor_id: str) -> DonorMemory | None: ...

    def put_donor_memory(self, memory: DonorMemory) -> None: ...


class DynamoRepository:
    def __init__(
        self,
        client=None,
        *,
        cases_table: str | None = None,
        events_table: str | None = None,
        donors_table: str | None = None,
        outreach_table: str | None = None,
        approvals_table: str | None = None,
        tasks_table: str | None = None,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.client = client or boto3.client("dynamodb")
        self.cases_table = cases_table or os.environ["CASES_TABLE"]
        self.events_table = events_table or os.environ["EVENTS_TABLE"]
        self.donors_table = donors_table or os.environ["DONORS_TABLE"]
        self.outreach_table = outreach_table or os.environ["OUTREACH_TABLE"]
        self.approvals_table = approvals_table or os.environ["APPROVALS_TABLE"]
        self.tasks_table = tasks_table or os.environ["TASKS_TABLE"]
        self.clock = clock or (
            lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.serializer = TypeSerializer()
        self.deserializer = TypeDeserializer()

    def get_case(self, case_id: str) -> CaseRecord | None:
        response = self.client.get_item(
            TableName=self.cases_table,
            Key={"id": {"S": case_id}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        return CaseRecord.model_validate(self._deserialize_item(item))

    def put_case(self, case: CaseRecord) -> None:
        self.client.put_item(
            TableName=self.cases_table,
            Item=self._serialize_item(case),
        )

    def list_cases(self) -> list[CaseRecord]:
        response = self.client.scan(TableName=self.cases_table)
        return [
            CaseRecord.model_validate(self._deserialize_item(item))
            for item in response.get("Items", [])
            if item.get("record_type", {}).get("S") != "IDEMPOTENCY"
        ]

    def find_idempotent_case(
        self, owner_email: str, key: str
    ) -> CaseRecord | None:
        response = self.client.get_item(
            TableName=self.cases_table,
            Key={"id": {"S": self._idempotency_id(owner_email, key)}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        case_id = self.deserializer.deserialize(item["case_id"])
        return self.get_case(case_id)

    def put_idempotency(
        self, owner_email: str, key: str, case_id: str
    ) -> None:
        item = {
            "id": self._idempotency_id(owner_email, key),
            "record_type": "IDEMPOTENCY",
            "owner_email": owner_email,
            "idempotency_key": key,
            "case_id": case_id,
        }
        self.client.put_item(
            TableName=self.cases_table,
            Item=self._serialize_item(item),
            ConditionExpression="attribute_not_exists(id)",
        )

    def append_event(
        self, case_id: str, event_type: str, payload: dict
    ) -> None:
        timestamp = self._normalize_timestamp(self.clock())
        event_id = self.id_factory()
        event = {
            "event_id": event_id,
            "case_id": case_id,
            "event_key": f"{timestamp}#{event_id}",
            "type": event_type,
            "timestamp": timestamp,
            "payload": payload,
        }
        self.client.put_item(
            TableName=self.events_table,
            Item=self._serialize_item(event),
        )

    def create_case_with_event(
        self,
        case: CaseRecord,
        owner_email: str,
        key: str,
        request_hash: str,
        event: dict,
    ) -> CaseRecord:
        transaction = self._create_transaction(
            case, owner_email, key, request_hash, event
        )
        try:
            self.client.transact_write_items(**transaction)
            return case
        except ClientError as error:
            if (
                error.response.get("Error", {}).get("Code")
                != "TransactionCanceledException"
            ):
                raise
            cancellation_reasons = error.response.get(
                "CancellationReasons"
            )
            if cancellation_reasons is not None and not any(
                reason.get("Code") == "ConditionalCheckFailed"
                for reason in cancellation_reasons
            ):
                raise

            winner = self._get_idempotency(owner_email, key)
            if winner is None:
                raise
            if winner.get("request_hash") != request_hash:
                raise IdempotencyConflict(
                    "idempotency key was already used for another request"
                ) from error
            existing = self.get_case(winner["case_id"])
            if existing is None:
                raise
            return existing

    def get_donor(self, donor_id: str) -> Donor | None:
        response = self.client.get_item(
            TableName=self.donors_table,
            Key={"id": {"S": donor_id}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        return Donor.model_validate(self._deserialize_item(item))

    def put_donor(self, donor: Donor) -> None:
        self.client.put_item(
            TableName=self.donors_table,
            Item=self._serialize_item(donor),
        )

    def list_donors(self) -> list[Donor]:
        response = self.client.scan(TableName=self.donors_table)
        return [
            Donor.model_validate(self._deserialize_item(item))
            for item in response.get("Items", [])
            if "blood_group" in item
        ]

    def get_approval(self, approval_id: str) -> Approval | None:
        response = self.client.get_item(
            TableName=self.approvals_table,
            Key={"id": {"S": approval_id}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        return Approval.model_validate(self._deserialize_item(item))

    def put_approval(self, approval: Approval) -> None:
        self.client.put_item(
            TableName=self.approvals_table,
            Item=self._serialize_item(approval),
        )

    def list_approvals(self) -> list[Approval]:
        response = self.client.scan(TableName=self.approvals_table)
        return [
            Approval.model_validate(self._deserialize_item(item))
            for item in response.get("Items", [])
        ]

    def claim_approval_for_send(
        self, approval_id: str, admin_email: str
    ) -> Approval | None:
        timestamp = self._normalize_timestamp(self.clock())
        try:
            response = self.client.update_item(
                TableName=self.approvals_table,
                Key={"id": {"S": approval_id}},
                UpdateExpression=(
                    "SET #status = :sending, decided_by = :admin_email, "
                    "decided_at = :decided_at"
                ),
                ConditionExpression="#status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":sending": {"S": "sending"},
                    ":pending": {"S": "pending"},
                    ":admin_email": {"S": admin_email},
                    ":decided_at": {"S": timestamp},
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as error:
            if (
                error.response.get("Error", {}).get("Code")
                != "ConditionalCheckFailedException"
            ):
                raise
            existing = self.get_approval(approval_id)
            if existing is not None and existing.status == "approved":
                return existing
            return None
        return Approval.model_validate(
            self._deserialize_item(response["Attributes"])
        )

    def record_attempt(
        self,
        case_id: str,
        donor_id: str,
        channel: str,
        status: str,
        sent_message_id: str | None,
    ) -> MessageAttempt:
        timestamp = self._normalize_timestamp(self.clock())
        attempt = MessageAttempt(
            case_id=case_id,
            donor_id=donor_id,
            channel=channel,
            status=status,
            sent_message_id=sent_message_id,
            attempted_at=datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            ),
        )
        attempt_id = self.id_factory()
        item = {
            "id": attempt_id,
            "attempt_key": f"{donor_id}#{timestamp}#{attempt_id}",
            **attempt.model_dump(mode="json"),
        }
        self.client.put_item(
            TableName=self.outreach_table,
            Item=self._serialize_item(item),
        )
        return attempt

    def count_attempts(self, case_id: str, donor_id: str) -> int:
        response = self.client.query(
            TableName=self.outreach_table,
            KeyConditionExpression=(
                "case_id = :case_id AND begins_with("
                "attempt_key, :attempt_prefix)"
            ),
            ExpressionAttributeValues={
                ":case_id": {"S": case_id},
                ":attempt_prefix": {"S": f"{donor_id}#"},
            },
            Select="COUNT",
            ConsistentRead=True,
        )
        return int(response["Count"])

    def create_task(self, task: EscalationTask) -> EscalationTask:
        self.client.put_item(
            TableName=self.tasks_table,
            Item=self._serialize_item(task),
        )
        return task

    def list_tasks(self) -> list[EscalationTask]:
        response = self.client.scan(TableName=self.tasks_table)
        return [
            EscalationTask.model_validate(self._deserialize_item(item))
            for item in response.get("Items", [])
        ]

    def put_task(self, task: EscalationTask) -> None:
        self.client.put_item(
            TableName=self.tasks_table,
            Item=self._serialize_item(task),
        )

    def get_donor_memory(self, donor_id: str) -> DonorMemory | None:
        response = self.client.get_item(
            TableName=self.donors_table,
            Key={"id": {"S": self._donor_memory_id(donor_id)}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        return DonorMemory.model_validate(self._deserialize_item(item))

    def put_donor_memory(self, memory: DonorMemory) -> None:
        item = {
            "id": self._donor_memory_id(memory.donor_id),
            **memory.model_dump(mode="json"),
        }
        self.client.put_item(
            TableName=self.donors_table,
            Item=self._serialize_item(item),
        )

    def _create_transaction(
        self,
        case: CaseRecord,
        owner_email: str,
        key: str,
        request_hash: str,
        event: dict,
    ) -> dict:
        timestamp = self._normalize_timestamp(event["timestamp"])
        event_id = event["event_id"]
        event_item = {
            **event,
            "case_id": case.id,
            "timestamp": timestamp,
            "event_key": f"{timestamp}#{event_id}",
        }
        idempotency_item = {
            "id": self._idempotency_id(owner_email, key),
            "record_type": "IDEMPOTENCY",
            "owner_email": owner_email,
            "idempotency_key": key,
            "case_id": case.id,
            "request_hash": request_hash,
        }
        return {
            "TransactItems": [
                {
                    "Put": {
                        "TableName": self.cases_table,
                        "Item": self._serialize_item(case),
                        "ConditionExpression": "attribute_not_exists(id)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.cases_table,
                        "Item": self._serialize_item(idempotency_item),
                        "ConditionExpression": "attribute_not_exists(id)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.events_table,
                        "Item": self._serialize_item(event_item),
                        "ConditionExpression": (
                            "attribute_not_exists(case_id) AND "
                            "attribute_not_exists(event_key)"
                        ),
                    }
                },
            ]
        }

    def _get_idempotency(
        self, owner_email: str, key: str
    ) -> dict | None:
        response = self.client.get_item(
            TableName=self.cases_table,
            Key={"id": {"S": self._idempotency_id(owner_email, key)}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return self._deserialize_item(item) if item is not None else None

    def _serialize_item(self, item: BaseModel | dict) -> dict:
        normalized = self._normalize(item)
        return {
            key: self.serializer.serialize(value)
            for key, value in normalized.items()
        }

    def _deserialize_item(self, item: dict) -> dict:
        return {
            key: self.deserializer.deserialize(value)
            for key, value in item.items()
        }

    def _normalize(self, value):
        if isinstance(value, BaseModel):
            return self._normalize(value.model_dump())
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("datetime must be timezone-aware")
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Enum):
            return self._normalize(value.value)
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, dict):
            return {
                key: self._normalize(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._normalize(item) for item in value]
        return value

    @staticmethod
    def _normalize_timestamp(value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _idempotency_id(owner_email: str, key: str) -> str:
        return f"IDEMPOTENCY#{owner_email}#{key}"

    @staticmethod
    def _donor_memory_id(donor_id: str) -> str:
        return f"MEMORY#{donor_id}"
