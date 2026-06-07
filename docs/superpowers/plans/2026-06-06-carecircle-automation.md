# CareCircle Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a persistent Python automation service that coordinates a blood request from intake through planning, approved outreach, donor response, escalation, coordination, and closure.

**Architecture:** A Python Lambda exposes API Gateway endpoints and owns all case mutations. Focused domain modules implement deterministic medical compatibility, ranking, workflow transitions, approval gates, and message scheduling; adapters isolate DynamoDB, Bedrock, SES, and simulation behavior. The existing frontend becomes an API client and stops treating browser storage as the source of truth.

**Tech Stack:** Python 3.12, FastAPI, Mangum, boto3, Pydantic, pytest, AWS Lambda, API Gateway HTTP API, DynamoDB, Step Functions, EventBridge Scheduler, Bedrock, SES, S3, CloudWatch, vanilla JavaScript.

---

## File Structure

Create the backend under `iii-project/automation/`:

- `app/main.py`: FastAPI routes and dependency wiring.
- `app/models.py`: API and domain models.
- `app/auth.py`: validation of existing CareCircle HMAC session tokens.
- `app/compatibility.py`: deterministic red-cell compatibility rules.
- `app/ranking.py`: donor eligibility, fatigue, and ranking.
- `app/workflow.py`: state transitions and orchestration decisions.
- `app/services.py`: use cases for cases, approvals, responses, and closure.
- `app/repositories.py`: repository protocols and DynamoDB implementation.
- `app/messaging.py`: simulation and SES/SNS adapters.
- `app/ai.py`: Bedrock request extraction and ambiguous response classification.
- `app/handler.py`: Mangum Lambda entry point.
- `tests/`: unit and API integration tests.
- `requirements.txt`: runtime dependencies.
- `requirements-dev.txt`: test dependencies.
- `template.yaml`: CloudFormation infrastructure.
- `state_machine.asl.json`: Step Functions definition.
- `scripts/package.ps1`: reproducible Lambda package creation.
- `scripts/deploy.ps1`: CloudFormation package/deploy and outputs.

Modify the frontend:

- `iii-project/aws-config.js`: automation API URL.
- `iii-project/app.js`: automation API client and request/admin/Hoon Buddy integration.
- `iii-project/carecircle-core.js`: cloud response persistence bridge.
- `iii-project/carecircle-pages.js`: cloud outreach and donor response views.
- `iii-project/admin.html`: approval queue and workflow event timeline.
- `iii-project/request.html`: cloud state and retry/error presentation.
- `iii-project/outreach.html`: real workflow queue controls.
- `iii-project/donor-response.html`: tokenized cloud response submission.

## Task 1: Python Service Skeleton and Health Endpoint

**Files:**
- Create: `iii-project/automation/app/__init__.py`
- Create: `iii-project/automation/app/main.py`
- Create: `iii-project/automation/app/handler.py`
- Create: `iii-project/automation/requirements.txt`
- Create: `iii-project/automation/requirements-dev.txt`
- Create: `iii-project/automation/tests/test_health.py`

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from app.main import create_app


def test_health_reports_simulation_mode():
    client = TestClient(create_app())
    response = client.get("/automation/health")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "carecircle-automation",
        "outreachMode": "simulation",
    }
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
cd iii-project\automation
python -m pytest tests\test_health.py -v
```

Expected: collection fails because `app.main` does not exist.

- [ ] **Step 3: Add the minimal FastAPI app**

```python
# app/main.py
import os
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="CareCircle Automation")

    @app.get("/automation/health")
    def health() -> dict:
        return {
            "ok": True,
            "service": "carecircle-automation",
            "outreachMode": os.getenv("OUTREACH_MODE", "simulation"),
        }

    return app


app = create_app()
```

```python
# app/handler.py
from mangum import Mangum
from app.main import app

handler = Mangum(app)
```

Use these dependency files:

```text
# requirements.txt
fastapi==0.115.12
mangum==0.19.0
pydantic==2.11.5
boto3==1.38.32
```

```text
# requirements-dev.txt
-r requirements.txt
httpx==0.28.1
pytest==8.4.0
```

- [ ] **Step 4: Install dependencies and verify GREEN**

Run:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests\test_health.py -v
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```powershell
git add iii-project/automation
git commit -m "feat: scaffold Python automation API"
```

## Task 2: Domain Models, Compatibility, and Ranking

**Files:**
- Create: `iii-project/automation/app/models.py`
- Create: `iii-project/automation/app/compatibility.py`
- Create: `iii-project/automation/app/ranking.py`
- Create: `iii-project/automation/tests/test_compatibility.py`
- Create: `iii-project/automation/tests/test_ranking.py`

- [ ] **Step 1: Write failing compatibility tests**

```python
from app.compatibility import can_donate_red_cells


def test_o_negative_can_supply_any_red_cell_group():
    assert can_donate_red_cells("O-", "AB+") is True


def test_ab_positive_cannot_supply_o_negative():
    assert can_donate_red_cells("AB+", "O-") is False


def test_invalid_group_is_rejected():
    assert can_donate_red_cells("X", "O+") is False
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_compatibility.py -v`

Expected: import failure for `app.compatibility`.

- [ ] **Step 3: Implement deterministic compatibility**

```python
# app/compatibility.py
COMPATIBLE_RECIPIENTS = {
    "O-": {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "O+": {"O+", "A+", "B+", "AB+"},
    "A-": {"A-", "A+", "AB-", "AB+"},
    "A+": {"A+", "AB+"},
    "B-": {"B-", "B+", "AB-", "AB+"},
    "B+": {"B+", "AB+"},
    "AB-": {"AB-", "AB+"},
    "AB+": {"AB+"},
}


def can_donate_red_cells(donor_group: str, patient_group: str) -> bool:
    return patient_group.upper() in COMPATIBLE_RECIPIENTS.get(donor_group.upper(), set())
```

- [ ] **Step 4: Write failing ranking tests**

```python
from datetime import date, timedelta
from app.models import Donor, BloodRequest
from app.ranking import rank_donors


def test_ranking_filters_incompatible_and_ineligible_donors():
    request = BloodRequest(
        patient_name="Asha", blood_group="A+", units=1,
        hospital="City Hospital", city="Dehradun",
        deadline=date.today() + timedelta(days=3), urgency="high",
    )
    donors = [
        Donor(id="D1", name="Near", blood_group="A+", city="Dehradun",
              eligible=True, reliability=90, fatigue=10),
        Donor(id="D2", name="Wrong", blood_group="B+", city="Dehradun",
              eligible=True, reliability=99, fatigue=0),
        Donor(id="D3", name="Blocked", blood_group="O-", city="Dehradun",
              eligible=False, reliability=99, fatigue=0),
    ]
    ranked = rank_donors(request, donors)
    assert [item.donor.id for item in ranked] == ["D1"]
```

- [ ] **Step 5: Add models and minimal ranking implementation**

```python
# app/models.py
from datetime import date, datetime
from enum import StrEnum
from pydantic import BaseModel, Field


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


class RankedDonor(BaseModel):
    donor: Donor
    score: int
    reasons: list[str]


class CaseRecord(BaseModel):
    id: str
    owner_email: str
    request: BloodRequest
    state: CaseState
    escalation_level: int = 0
    created_at: datetime
    updated_at: datetime
```

```python
# app/ranking.py
from app.compatibility import can_donate_red_cells
from app.models import BloodRequest, Donor, RankedDonor


def rank_donors(request: BloodRequest, donors: list[Donor]) -> list[RankedDonor]:
    ranked = []
    for donor in donors:
        if donor.opted_out or not donor.eligible:
            continue
        if not can_donate_red_cells(donor.blood_group, request.blood_group):
            continue
        same_city = donor.city.casefold() == request.city.casefold()
        exact_group = donor.blood_group == request.blood_group
        score = donor.reliability - donor.fatigue // 2
        score += 20 if same_city else 0
        score += 15 if exact_group else 5
        ranked.append(RankedDonor(
            donor=donor,
            score=max(0, min(100, score)),
            reasons=[
                "compatible",
                "same city" if same_city else "outside city",
                "exact group" if exact_group else "compatible group",
            ],
        ))
    return sorted(ranked, key=lambda item: item.score, reverse=True)
```

- [ ] **Step 6: Run all domain tests**

Run: `python -m pytest tests/test_compatibility.py tests/test_ranking.py -v`

Expected: `4 passed`.

- [ ] **Step 7: Commit**

```powershell
git add iii-project/automation/app iii-project/automation/tests
git commit -m "feat: add blood compatibility and donor ranking"
```

## Task 3: Workflow State Machine and Plans

**Files:**
- Create: `iii-project/automation/app/workflow.py`
- Create: `iii-project/automation/tests/test_workflow.py`

- [ ] **Step 1: Write failing transition and plan tests**

```python
import pytest
from app.models import CaseState
from app.workflow import build_outreach_plan, transition


def test_case_cannot_skip_from_draft_to_fulfilled():
    with pytest.raises(ValueError, match="Invalid transition"):
        transition(CaseState.DRAFT, CaseState.FULFILLED)


def test_ranked_donors_are_split_into_primary_backup_and_emergency():
    ids = [f"D{i}" for i in range(10)]
    plan = build_outreach_plan(ids, units=2)
    assert plan == {
        "primary": ["D0", "D1", "D2", "D3"],
        "backup": ["D4", "D5", "D6", "D7"],
        "emergency": ["D8", "D9"],
    }
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_workflow.py -v`

Expected: import failure for `app.workflow`.

- [ ] **Step 3: Implement allowed transitions and circle sizing**

```python
# app/workflow.py
from app.models import CaseState

ALLOWED_TRANSITIONS = {
    CaseState.DRAFT: {CaseState.NEEDS_INFORMATION, CaseState.PLANNED, CaseState.CANCELLED},
    CaseState.NEEDS_INFORMATION: {CaseState.PLANNED, CaseState.CANCELLED, CaseState.EXPIRED},
    CaseState.PLANNED: {CaseState.AWAITING_APPROVAL, CaseState.OUTREACH_ACTIVE, CaseState.CANCELLED},
    CaseState.AWAITING_APPROVAL: {CaseState.OUTREACH_ACTIVE, CaseState.CANCELLED},
    CaseState.OUTREACH_ACTIVE: {
        CaseState.DONOR_CONFIRMED, CaseState.UNFULFILLED,
        CaseState.CANCELLED, CaseState.EXPIRED,
    },
    CaseState.DONOR_CONFIRMED: {CaseState.COORDINATING, CaseState.CANCELLED},
    CaseState.COORDINATING: {CaseState.FULFILLED, CaseState.CANCELLED, CaseState.UNFULFILLED},
}


def transition(current: CaseState, target: CaseState) -> CaseState:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid transition: {current} -> {target}")
    return target


def build_outreach_plan(donor_ids: list[str], units: int) -> dict[str, list[str]]:
    primary_size = max(2, units * 2)
    backup_size = max(2, units * 2)
    return {
        "primary": donor_ids[:primary_size],
        "backup": donor_ids[primary_size:primary_size + backup_size],
        "emergency": donor_ids[primary_size + backup_size:],
    }
```

- [ ] **Step 4: Run and verify GREEN**

Run: `python -m pytest tests/test_workflow.py -v`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
git add iii-project/automation/app/workflow.py iii-project/automation/tests/test_workflow.py
git commit -m "feat: add case workflow state machine"
```

## Task 4: Repository Layer, Case Service, and Audit Events

**Files:**
- Create: `iii-project/automation/app/repositories.py`
- Create: `iii-project/automation/app/services.py`
- Create: `iii-project/automation/tests/fakes.py`
- Create: `iii-project/automation/tests/test_case_service.py`

- [ ] **Step 1: Write a failing persistent-case service test**

```python
from datetime import date
from app.models import BloodRequest, CaseState
from app.services import CaseService
from tests.fakes import MemoryRepository


def test_create_case_persists_case_and_audit_event():
    repo = MemoryRepository()
    service = CaseService(repo=repo, clock=lambda: "2026-06-06T12:00:00Z")
    case = service.create_case(
        owner_email="patient@example.com",
        request=BloodRequest(
            patient_name="Asha", blood_group="O-", units=1,
            hospital="Doon Hospital", city="Dehradun",
            deadline=date(2026, 6, 9), urgency="critical",
        ),
        idempotency_key="request-1",
    )
    assert case.state == CaseState.DRAFT
    assert repo.events[0]["type"] == "CASE_CREATED"
    assert service.create_case(
        "patient@example.com", case.request, "request-1"
    ).id == case.id
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_case_service.py -v`

Expected: import failure for `app.services`.

- [ ] **Step 3: Implement repository protocols and memory fake**

Define `CaseRepository` with:

```python
class CaseRepository(Protocol):
    def get_case(self, case_id: str) -> CaseRecord | None: ...
    def put_case(self, case: CaseRecord) -> None: ...
    def find_idempotent_case(self, owner_email: str, key: str) -> CaseRecord | None: ...
    def put_idempotency(self, owner_email: str, key: str, case_id: str) -> None: ...
    def append_event(self, case_id: str, event_type: str, payload: dict) -> None: ...
```

Implement `MemoryRepository` in `tests/fakes.py` with dictionaries for cases
and idempotency entries plus a list for events.

- [ ] **Step 4: Implement minimal `CaseService.create_case`**

```python
class CaseService:
    def __init__(self, repo, clock, id_factory=lambda: str(uuid.uuid4())):
        self.repo = repo
        self.clock = clock
        self.id_factory = id_factory

    def create_case(self, owner_email, request, idempotency_key):
        existing = self.repo.find_idempotent_case(owner_email, idempotency_key)
        if existing:
            return existing
        now = datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
        case = CaseRecord(
            id=self.id_factory(), owner_email=owner_email, request=request,
            state=CaseState.DRAFT, created_at=now, updated_at=now,
        )
        self.repo.put_case(case)
        self.repo.put_idempotency(owner_email, idempotency_key, case.id)
        self.repo.append_event(case.id, "CASE_CREATED", {"owner": owner_email})
        return case
```

- [ ] **Step 5: Add DynamoDB repository tests using botocore Stubber**

Test that `DynamoRepository.put_case` writes to `CareCircleCases`, and
`append_event` writes to `CareCircleEvents` with ISO timestamps and case IDs.

- [ ] **Step 6: Implement `DynamoRepository`**

Use low-level `boto3.client("dynamodb")`, `TypeSerializer`, and
`TypeDeserializer`. Table names must come from environment variables:
`CASES_TABLE`, `EVENTS_TABLE`, `DONORS_TABLE`, `OUTREACH_TABLE`,
`APPROVALS_TABLE`, and `TASKS_TABLE`.

- [ ] **Step 7: Run repository and service tests**

Run: `python -m pytest tests/test_case_service.py tests/test_repositories.py -v`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add iii-project/automation
git commit -m "feat: persist cases and audit events"
```

## Task 5: Bedrock Intake, Reply Classification, and Authentication

**Files:**
- Create: `iii-project/automation/app/ai.py`
- Create: `iii-project/automation/app/auth.py`
- Create: `iii-project/automation/tests/test_ai.py`
- Create: `iii-project/automation/tests/test_auth.py`

- [ ] **Step 1: Write failing deterministic reply tests**

```python
from app.ai import classify_known_reply


def test_acceptance_is_classified_without_bedrock():
    result = classify_known_reply("Yes, I can donate tomorrow")
    assert result.status == "accepted"
    assert result.needs_ai is False


def test_unclear_reply_requires_bedrock():
    result = classify_known_reply("Maybe, let me see")
    assert result.status == "unclear"
    assert result.needs_ai is True
```

- [ ] **Step 2: Write failing token validation tests**

```python
import time
from app.auth import sign_test_token, validate_token


def test_valid_token_returns_role_and_email():
    token = sign_test_token(
        {"email": "admin@example.com", "role": "admin", "exp": int(time.time() * 1000) + 60000},
        "test-secret",
    )
    principal = validate_token(token, "test-secret")
    assert principal.email == "admin@example.com"
    assert principal.role == "admin"
```

- [ ] **Step 3: Run and verify RED**

Run: `python -m pytest tests/test_ai.py tests/test_auth.py -v`

Expected: imports fail.

- [ ] **Step 4: Implement local classification and Bedrock adapter**

`classify_known_reply` maps explicit acceptance, decline, unavailable, and
opt-out terms locally. `BedrockAdapter.classify_reply` calls Converse with
Amazon Nova Micro and requests JSON:

```json
{
  "status": "accepted|declined|unavailable|unclear|opt_out",
  "confidence": 0.0,
  "available_from": null,
  "location": null,
  "notes": ""
}
```

`BedrockAdapter.extract_request` requests the exact `BloodRequest` fields and a
`missing_fields` list. Parse JSON strictly and reject output that fails Pydantic
validation.

- [ ] **Step 5: Implement existing HMAC token validation**

Split `<payload>.<signature>`, recompute HMAC SHA-256 with `AUTH_SECRET`,
compare using `hmac.compare_digest`, decode base64url JSON, reject expired
tokens, and return:

```python
class Principal(BaseModel):
    email: str
    role: str
    display_name: str | None = None
    linked_id: str | None = None
```

- [ ] **Step 6: Run and verify GREEN**

Run: `python -m pytest tests/test_ai.py tests/test_auth.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add iii-project/automation/app iii-project/automation/tests
git commit -m "feat: add Bedrock understanding and API authentication"
```

## Task 6: Approval-Gated Messaging, Follow-Up, and Escalation

**Files:**
- Create: `iii-project/automation/app/messaging.py`
- Extend: `iii-project/automation/app/services.py`
- Create: `iii-project/automation/tests/test_outreach_service.py`

- [ ] **Step 1: Write failing approval-gate tests**

```python
def test_real_email_is_not_sent_before_admin_approval():
    repo = MemoryRepository()
    messenger = RecordingMessenger()
    service = OutreachService(repo, messenger, mode="email")
    approval = service.prepare(case_id="C1", donor_id="D1", channel="email")
    assert approval.status == "pending"
    assert messenger.sent == []


def test_approved_email_is_sent_once():
    repo = MemoryRepository()
    messenger = RecordingMessenger()
    service = OutreachService(repo, messenger, mode="email")
    approval = service.prepare("C1", "D1", "email")
    service.approve(approval.id, admin_email="admin@example.com")
    service.approve(approval.id, admin_email="admin@example.com")
    assert len(messenger.sent) == 1
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_outreach_service.py -v`

Expected: `OutreachService` is missing.

- [ ] **Step 3: Implement messaging adapters**

Provide:

- `SimulationMessenger.send(message)` returning `sim-<uuid>`.
- `SesMessenger.send(message)` calling `ses.send_email` with
  `SES_FROM_EMAIL`.
- `SnsMessenger.send(message)` calling `sns.publish`, but reject calls unless
  `ENABLE_SMS=true`.
- `RecordingMessenger` test fake.

All messages include a signed donor response URL and never expose patient
contact details.

- [ ] **Step 4: Implement approval, retry, and escalation use cases**

`OutreachService.prepare` creates a pending approval in real modes and creates
an immediately completed simulated attempt in simulation mode.

`approve` must:

1. require an admin principal;
2. use a conditional write from `pending` to `approved`;
3. send once;
4. record `MESSAGE_SENT`;
5. schedule a follow-up using EventBridge Scheduler.

`process_follow_up` must skip accepted, opted-out, closed, or expired cases. At
the retry limit it activates the next donor circle and appends
`ESCALATION_ADVANCED`.

- [ ] **Step 5: Persist engagement memory and operational tasks**

On every response, update the donor's response totals, acceptance ratio,
last-contact timestamp, opt-out flag, fatigue score, and next eligibility when
a donation is completed. Escalation must create explicit volunteer,
blood-bank-call, or Blood Warrior tasks instead of claiming those parties were
contacted. Add tests proving an opt-out is permanent and a completed donation
changes future ranking.

- [ ] **Step 6: Verify service behavior**

Run: `python -m pytest tests/test_outreach_service.py -v`

Expected: approval, deduplication, suppression, and escalation tests pass.

- [ ] **Step 7: Commit**

```powershell
git add iii-project/automation
git commit -m "feat: add approved outreach and escalation automation"
```

## Task 7: API Routes and End-to-End In-Memory Workflow

**Files:**
- Extend: `iii-project/automation/app/main.py`
- Create: `iii-project/automation/app/dependencies.py`
- Create: `iii-project/automation/tests/test_api_workflow.py`

- [ ] **Step 1: Write the failing API lifecycle test**

```python
def test_simulated_case_lifecycle(api_client, patient_token, admin_token):
    created = api_client.post(
        "/automation/cases",
        headers={"Authorization": f"Bearer {patient_token}", "Idempotency-Key": "case-1"},
        json={
            "patient_name": "Asha", "blood_group": "O-", "units": 1,
            "hospital": "Doon Hospital", "city": "Dehradun",
            "deadline": "2026-06-10", "urgency": "critical",
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    planned = api_client.post(
        f"/automation/cases/{case_id}/plan",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert planned.json()["state"] == "PLANNED"

    started = api_client.post(
        f"/automation/cases/{case_id}/start",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert started.json()["state"] == "OUTREACH_ACTIVE"

    response = api_client.post(
        f"/automation/cases/{case_id}/responses",
        json={"donor_id": "D1", "status": "accepted"},
    )
    assert response.json()["state"] == "DONOR_CONFIRMED"

    closed = api_client.post(
        f"/automation/cases/{case_id}/close",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"outcome": "fulfilled"},
    )
    assert closed.json()["state"] == "FULFILLED"
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_api_workflow.py -v`

Expected: first missing route returns `404`.

- [ ] **Step 3: Implement route dependencies**

`dependencies.py` selects DynamoDB and AWS adapters in Lambda, while tests
override dependencies with memory repositories and recording adapters.

- [ ] **Step 4: Implement the API contract**

Add all routes from the design:

- create/list/get/answer/plan/start/respond/coordinate/close cases;
- list/approve/reject approvals;
- list/complete tasks;
- assistant with proposed actions.

Use `Authorization: Bearer <token>`, enforce ownership for patient reads, and
require admin or volunteer permissions for coordination endpoints.

- [ ] **Step 5: Run full backend suite**

Run: `python -m pytest -v`

Expected: all tests pass with no network calls.

- [ ] **Step 6: Commit**

```powershell
git add iii-project/automation
git commit -m "feat: expose automated case lifecycle API"
```

## Task 8: AWS Infrastructure and Simulation Deployment

**Files:**
- Create: `iii-project/automation/template.yaml`
- Create: `iii-project/automation/state_machine.asl.json`
- Create: `iii-project/automation/scripts/package.ps1`
- Create: `iii-project/automation/scripts/deploy.ps1`
- Create: `iii-project/automation/tests/test_template.py`

- [ ] **Step 1: Write a failing infrastructure contract test**

Parse `template.yaml` with `yaml.safe_load` and assert it defines:

- six DynamoDB tables using `PAY_PER_REQUEST`;
- one Python 3.12 Lambda;
- one API Gateway HTTP API;
- one Step Functions state machine;
- least-privilege Bedrock, SES, Scheduler, DynamoDB, S3, and log permissions;
- environment `OUTREACH_MODE=simulation`;
- CloudWatch log retention;
- outputs `AutomationApiUrl` and `AutomationFunctionName`.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_template.py -v`

Expected: missing `template.yaml`.

- [ ] **Step 3: Add CloudFormation and state machine**

The state machine invokes worker operations:

`plan -> prepare_primary -> wait_for_response -> evaluate -> follow_up |
escalate -> coordinate -> close`.

All waits and retries are bounded. State input contains IDs only; sensitive
records remain in DynamoDB.

- [ ] **Step 4: Add packaging and deployment scripts**

`package.ps1` must:

1. remove only `automation/.build`;
2. install `requirements.txt` into `.build`;
3. copy `app`;
4. zip to `carecircle-automation.zip`.

`deploy.ps1` must:

1. upload the zip to the existing deployment S3 bucket or create a dedicated
   bucket;
2. run `aws cloudformation deploy --capabilities CAPABILITY_NAMED_IAM`;
3. pass `AuthSecret`, `SesFromEmail`, Bedrock model, and simulation mode;
4. print stack outputs.

- [ ] **Step 5: Verify template and package**

Run:

```powershell
python -m pytest tests/test_template.py -v
.\scripts\package.ps1
python -c "import zipfile; z=zipfile.ZipFile('carecircle-automation.zip'); assert 'app/handler.py' in z.namelist()"
```

Expected: tests pass and archive assertion exits `0`.

- [ ] **Step 6: Deploy simulation stack**

Run:

```powershell
.\scripts\deploy.ps1 -Region ap-south-1 -OutreachMode simulation `
  -SesFromEmail anshulnautiyal2006@gmail.com
```

Expected: stack reaches `CREATE_COMPLETE` or `UPDATE_COMPLETE` and prints the
automation API URL.

- [ ] **Step 7: Run AWS smoke test**

Call `/automation/health`, create a test case, start simulated outreach, submit
an accepted response, and query the event history. Verify DynamoDB contains the
case and audit events.

- [ ] **Step 8: Commit**

```powershell
git add iii-project/automation
git commit -m "infra: deploy CareCircle automation on AWS"
```

## Task 9: Frontend Cloud Integration

**Files:**
- Modify: `iii-project/aws-config.js`
- Modify: `iii-project/app.js`
- Modify: `iii-project/carecircle-core.js`
- Modify: `iii-project/carecircle-pages.js`
- Modify: `iii-project/admin.html`
- Modify: `iii-project/request.html`
- Modify: `iii-project/outreach.html`
- Modify: `iii-project/donor-response.html`
- Create: `iii-project/tests/frontend-automation.test.mjs`

- [ ] **Step 1: Write a failing browser-independent frontend API test**

Test a new `CareCircleAutomation` client against a local mock HTTP server:

```javascript
const created = await client.createCase(payload, "case-key-1");
assert.equal(created.state, "DRAFT");
assert.equal(requests[0].headers["idempotency-key"], "case-key-1");
assert.match(requests[0].headers.authorization, /^Bearer /);
```

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/frontend-automation.test.mjs`

Expected: client is undefined.

- [ ] **Step 3: Add the automation API client**

Expose:

```javascript
window.CareCircleAutomation = {
  baseUrl: window.CARECIRCLE_AUTOMATION_API_BASE_URL,
  request(path, options),
  createCase(payload, idempotencyKey),
  getCase(caseId),
  listCases(),
  planCase(caseId),
  startCase(caseId),
  submitResponse(caseId, payload),
  listApprovals(),
  approve(approvalId),
  reject(approvalId),
  closeCase(caseId, outcome)
};
```

The client reads the existing cloud auth token from `localStorage`, parses JSON
errors, and throws a typed error with status and message.

- [ ] **Step 4: Replace request and Hoon Buddy local mutations**

On `request.html`, submit to `POST /automation/cases`, store only the latest
case ID locally, and render the returned cloud record.

Hoon Buddy must return a proposed action, ask the user to confirm it, then call
the case API. It may not silently send messages or claim completion.

- [ ] **Step 5: Replace admin, outreach, and response local mutations**

- Admin queue lists cloud cases and approvals.
- Approve/reject buttons call cloud endpoints and refresh the queue.
- Outreach reads the server-generated plan and attempt states.
- Donor response submits a signed response token and current response.
- Family tracker renders server state and audit events.

Keep a visible simulation badge while `outreachMode` is simulation.

- [ ] **Step 6: Run frontend and backend checks**

Run:

```powershell
node --test tests/frontend-automation.test.mjs
npm run check
```

Expected: all tests pass and JavaScript syntax checks exit `0`.

- [ ] **Step 7: Commit**

```powershell
git add iii-project
git commit -m "feat: connect CareCircle UI to automation API"
```

## Task 10: SES Verification, Real Email Gate, and End-to-End Browser Test

**Files:**
- Modify: `iii-project/automation/template.yaml`
- Modify: `iii-project/automation/scripts/deploy.ps1`
- Create: `iii-project/automation/tests/aws_smoke.py`
- Create: `iii-project/tests/e2e-automation.md`

- [ ] **Step 1: Request SES sender verification**

Run:

```powershell
aws sesv2 create-email-identity `
  --region ap-south-1 `
  --email-identity anshulnautiyal2006@gmail.com
```

The user must open the AWS verification email and approve it. Check status:

```powershell
aws sesv2 get-email-identity `
  --region ap-south-1 `
  --email-identity anshulnautiyal2006@gmail.com
```

Expected: `VerifiedForSendingStatus` is `true`.

- [ ] **Step 2: Keep SES sandbox restrictions explicit**

Before production access, only send to verified recipient identities. Do not
attempt to bypass SES sandbox. Add a dashboard warning when the account is
sandboxed.

- [ ] **Step 3: Deploy email mode**

Run:

```powershell
.\scripts\deploy.ps1 -Region ap-south-1 -OutreachMode email `
  -SesFromEmail anshulnautiyal2006@gmail.com
```

Expected: stack update completes.

- [ ] **Step 4: Verify approval gating with a verified test recipient**

Create a case and prepare outreach. Confirm no SES message exists before
approval. Approve it as admin, then confirm one message ID is recorded and a
second approval attempt does not send again.

- [ ] **Step 5: Run the complete browser workflow**

Using the in-app Browser:

1. sign in as patient and create a case;
2. refresh and verify the case persists;
3. sign in as admin and approve outreach;
4. open the donor response URL and accept;
5. verify follow-up is suppressed;
6. record coordination and close the case;
7. verify the patient tracker reaches `FULFILLED`;
8. inspect mobile and desktop layouts for errors and clipped controls.

- [ ] **Step 6: Run full verification**

Run:

```powershell
cd iii-project\automation
python -m pytest -v
cd ..
node --test tests/frontend-automation.test.mjs
npm run check
```

Expected: all tests pass with zero failures.

- [ ] **Step 7: Run CodeRabbit review**

Run:

```powershell
coderabbit review --agent -t uncommitted
```

Address critical and major issues, rerun affected tests, then rerun CodeRabbit.

- [ ] **Step 8: Commit final verification fixes**

```powershell
git add iii-project docs
git commit -m "test: verify automated blood coordination workflow"
```

## Task 11: Cost and Operational Guardrails

**Files:**
- Modify: `iii-project/aws-budget-carecircle.json`
- Modify: `iii-project/AWS_DEPLOYMENT.md`
- Create: `iii-project/automation/OPERATIONS.md`

- [ ] **Step 1: Add a cost configuration test**

Assert the budget limit is `40 USD`, SMS defaults off, DynamoDB uses on-demand
capacity, CloudWatch retention is bounded, and no NAT Gateway, RDS, SageMaker,
GPU, or provisioned Bedrock resources exist in the template.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_cost_controls.py -v`

Expected: fails until operations configuration is updated.

- [ ] **Step 3: Document operations**

Document:

- switching simulation/email modes;
- SES verification and sandbox status;
- disabling all outreach;
- replaying failed workflow steps;
- closing cases and cancelling schedules;
- CloudWatch log locations;
- DynamoDB backup/export;
- Bedrock throttling response;
- monthly budget alarm thresholds at 10, 20, 30, and 38 USD.

- [ ] **Step 4: Apply and verify the AWS budget**

Use `aws budgets describe-budget` before mutation, update the existing
CareCircle budget only if required, then describe it again and verify the limit
and alerts.

- [ ] **Step 5: Run all cost and regression tests**

Run: `python -m pytest -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add iii-project docs
git commit -m "docs: add automation operations and cost guardrails"
```
