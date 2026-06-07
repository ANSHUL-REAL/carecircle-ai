from datetime import datetime, date, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator


VALID_BLOOD_GROUPS = frozenset(
    {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"}
)


def normalize_blood_group(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in VALID_BLOOD_GROUPS:
        raise ValueError("invalid blood group")
    return normalized


class CaseState(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    PLANNED = "PLANNED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    OUTREACH_ACTIVE = "OUTREACH_ACTIVE"
    DONOR_CONFIRMED = "DONOR_CONFIRMED"
    COORDINATING = "COORDINATING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNFULFILLED = "UNFULFILLED"


class BloodRequest(BaseModel):
    patient_name: str
    blood_group: str
    units: int = Field(ge=1, le=20)
    hospital: str
    city: str
    deadline: date
    urgency: str
    component: str = "red_cells"
    diagnosis: str | None = None

    _normalize_blood_group = field_validator("blood_group", mode="before")(
        normalize_blood_group
    )


class Donor(BaseModel):
    id: str
    name: str
    blood_group: str
    city: str
    eligible: bool
    reliability: int = Field(ge=0, le=100)
    fatigue: int = Field(ge=0, le=100)
    email: str | None = None
    phone: str | None = None
    opted_out: bool = False
    country: str | None = None
    gender: str = "Unknown"
    donor_type: str = "Emergency Donor"
    donations_till_date: int = 0
    total_calls: int = 0
    cycle_of_donations: int = 90
    active_status: str | None = None
    last_donation_date: date | None = None
    next_eligible_date: date | None = None

    _normalize_blood_group = field_validator("blood_group", mode="before")(
        normalize_blood_group
    )


class Message(BaseModel):
    case_id: str
    donor_id: str
    channel: str
    recipient: str
    subject: str
    body: str


class Approval(BaseModel):
    id: str
    case_id: str
    donor_id: str
    channel: str
    message: Message
    status: str = "pending"
    requested_at: AwareDatetime
    decided_at: AwareDatetime | None = None
    decided_by: str | None = None
    sent_message_id: str | None = None
    error_message: str | None = None


class MessageAttempt(BaseModel):
    case_id: str
    donor_id: str
    channel: str
    status: str
    sent_message_id: str | None = None
    attempted_at: AwareDatetime


class EscalationTask(BaseModel):
    id: str
    case_id: str
    donor_id: str
    kind: str
    status: str = "open"
    created_at: AwareDatetime


class DonorResponse(StrEnum):
    ACCEPTED = "accepted"
    DECLINED = "declined"
    OPTED_OUT = "opted_out"
    COMPLETED_DONATION = "completed_donation"


class DonorMemory(BaseModel):
    donor_id: str
    total_responses: int = Field(default=0, ge=0)
    accepted_responses: int = Field(default=0, ge=0)
    last_contacted_at: AwareDatetime | None = None
    opted_out: bool = False
    fatigue: int = Field(default=0, ge=0, le=100)
    next_eligible_at: AwareDatetime | None = None

    @property
    def acceptance_ratio(self) -> float:
        if self.total_responses == 0:
            return 0.0
        return self.accepted_responses / self.total_responses

    def with_response(
        self,
        response: DonorResponse,
        occurred_at: datetime,
    ) -> "DonorMemory":
        accepted = response in {
            DonorResponse.ACCEPTED,
            DonorResponse.COMPLETED_DONATION,
        }
        next_eligible_at = self.next_eligible_at
        if response is DonorResponse.COMPLETED_DONATION:
            next_eligible_at = occurred_at + timedelta(days=90)
        return self.model_copy(
            update={
                "total_responses": self.total_responses + 1,
                "accepted_responses": (
                    self.accepted_responses + (1 if accepted else 0)
                ),
                "last_contacted_at": occurred_at,
                "opted_out": self.opted_out
                or response is DonorResponse.OPTED_OUT,
                "fatigue": min(100, self.fatigue + 15),
                "next_eligible_at": next_eligible_at,
            }
        )


class RankedDonor(BaseModel):
    donor: Donor
    score: int
    reasons: list[str]


class CaseRecord(BaseModel):
    id: str
    owner_email: str
    request: BloodRequest
    state: CaseState
    escalation_level: int = Field(default=0, ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> "CaseRecord":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be on or after created_at")
        return self
