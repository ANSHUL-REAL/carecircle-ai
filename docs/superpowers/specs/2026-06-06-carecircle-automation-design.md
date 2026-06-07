# CareCircle Automation Architecture

## Goal

Convert CareCircle from browser-side demonstrations into a persistent blood
coordination system. A case must progress from a new request through donor
selection, outreach, response handling, follow-up, escalation, confirmation,
completion, and learning without relying on `localStorage`.

AWS is the only paid platform. External paid AI, messaging, database, and
workflow services are excluded.

## Delivery Phases

1. Build and test the complete workflow in simulation mode.
2. Enable Amazon SES email after sender and recipient verification.
3. Add Amazon SNS SMS behind the same approval gate.
4. Keep WhatsApp as a simulated adapter until a free Meta Cloud API setup is
   available.

## Architecture

The existing static website remains the user interface. It calls a Python
FastAPI-compatible Lambda API through API Gateway.

Core AWS services:

- API Gateway: authenticated HTTP endpoints.
- Lambda (Python): request handling, domain services, and worker actions.
- Step Functions: durable case orchestration and waits.
- DynamoDB: cases, donors, outreach attempts, responses, approvals, tasks,
  event history, and idempotency keys.
- Amazon Bedrock: structured request extraction and ambiguous reply
  classification.
- EventBridge Scheduler: delayed follow-ups and escalation wake-ups where a
  scheduler is more economical than long workflow waits.
- Amazon SES: approved email outreach.
- Amazon SNS: approved SMS outreach.
- S3: immutable extraction and audit artifacts.
- CloudWatch: logs, metrics, alarms, and workflow diagnostics.

The existing authentication Lambda continues to issue sessions. The automation
API validates those signed tokens and enforces patient, donor, volunteer, and
admin permissions.

## Agent Pipeline

### Request Intelligence Agent

Accepts structured form data, Hoon Buddy commands, or pasted notes. It extracts
patient name, blood group, component, units, hospital, city, deadline, urgency,
and recurrence information. Missing required fields produce one follow-up
question at a time.

### Decision Intelligence Engine

Calculates compatibility, eligibility, location relevance, reliability, donor
fatigue, urgency, and previous response behavior. It creates primary, backup,
volunteer, blood-bank, and Blood Warrior escalation stages.

### Donor Outreach Agent

Creates personalized outreach drafts for the best eligible donors. It never
sends a real message directly. Each real message becomes an approval item.
Simulation mode records the same attempt and generates no external contact.

### Response Understanding Agent

Processes response links and inbound reply text. Deterministic phrases are
classified locally. Bedrock handles unclear replies and returns structured
status, confidence, availability window, location, and notes. Low-confidence
results require human review.

### Follow-Up Agent

Schedules reminders for pending donors. It respects configurable contact
windows, retry limits, deduplication, donor fatigue, cancellation, and case
closure.

### Escalation Agent

Activates backup donors when primary capacity is insufficient. It then creates
volunteer tasks, suggests nearby blood banks, and opens Blood Warrior or admin
tasks. It never claims inventory or confirmation without an explicit response.

### Coordination Agent

Tracks accepted donors, required units, arrival estimates, check-in,
hospital confirmation, completion, cancellation, and exceptions. The case
closes only when an authorized coordinator records fulfillment or cancellation.

### Engagement and Memory Agent

Stores interaction outcomes, opt-out status, successful donations, reliability,
fatigue, and next eligibility. These records influence future ranking but do
not allow an LLM to modify medical compatibility rules.

## Case State Machine

Primary states:

`DRAFT -> NEEDS_INFORMATION -> PLANNED -> AWAITING_APPROVAL -> OUTREACH_ACTIVE
-> DONOR_CONFIRMED -> COORDINATING -> FULFILLED`

Alternative terminal states:

`CANCELLED`, `EXPIRED`, and `UNFULFILLED`.

Escalation is represented by a numeric level and event history rather than
overwriting the main state. Every transition is validated and idempotent.

## Data Model

The first release uses DynamoDB tables with on-demand capacity:

- `CareCircleCases`
- `CareCircleDonors`
- `CareCircleOutreach`
- `CareCircleApprovals`
- `CareCircleTasks`
- `CareCircleEvents`

Each item includes timestamps and ownership fields. Sensitive patient and donor
data is returned only to authorized roles. Contact details are never embedded
in public response URLs.

## API Contract

Initial endpoints:

- `POST /automation/cases`
- `GET /automation/cases/{case_id}`
- `GET /automation/cases`
- `POST /automation/cases/{case_id}/answers`
- `POST /automation/cases/{case_id}/plan`
- `POST /automation/cases/{case_id}/start`
- `POST /automation/cases/{case_id}/responses`
- `POST /automation/cases/{case_id}/coordinate`
- `POST /automation/cases/{case_id}/close`
- `GET /automation/approvals`
- `POST /automation/approvals/{approval_id}/approve`
- `POST /automation/approvals/{approval_id}/reject`
- `GET /automation/tasks`
- `POST /automation/tasks/{task_id}/complete`
- `POST /automation/assistant`

Hoon Buddy calls the assistant endpoint. The response contains conversational
text plus a proposed action. Mutating actions require explicit user
confirmation, and outbound communication additionally requires admin approval.

## Frontend Integration

The request form creates a cloud case. Patient, volunteer, outreach, donor,
admin, and Hoon Buddy pages read from the automation API instead of browser
storage. Existing static dataset donors can seed DynamoDB for demonstration.

The admin dashboard gains:

- pending message approvals;
- active workflow states;
- escalation and follow-up queues;
- case event timelines;
- simulation/real-send indicators;
- failure and retry controls.

## Safety and Error Handling

- Medical compatibility remains deterministic code.
- Bedrock produces suggestions and structured classifications, not diagnoses.
- Real outreach requires admin approval.
- Donor opt-outs immediately suppress future contact.
- API actions use idempotency keys to prevent duplicate requests and messages.
- Failed sends retry with bounded exponential backoff and then create an admin
  task.
- Expired or closed cases cancel pending schedules.
- All mutations append an audit event.
- Credentials stay in AWS IAM roles or Secrets Manager, never frontend files.

## Cost Controls

- Lambda and DynamoDB use on-demand/serverless modes.
- Bedrock uses Amazon Nova Micro with short structured prompts.
- Step Functions uses Standard only for durable case coordination; high-volume
  utility actions remain Lambda calls.
- EventBridge schedules are created only for active follow-ups and deleted on
  completion.
- S3 lifecycle rules expire nonessential extraction artifacts.
- CloudWatch log retention is limited.
- AWS Budget remains at 40 USD with alerts before the limit.
- SMS is disabled by default because SNS messages are billable.

## Testing

- Unit tests cover compatibility, ranking, state transitions, retry policy,
  reply classification, permissions, and idempotency.
- Integration tests use in-memory repository and fake Bedrock/messaging
  adapters.
- AWS smoke tests create a simulated case and verify persisted events.
- Browser tests cover patient request creation, admin approval, donor response,
  follow-up/escalation visibility, and case closure.
- A CodeRabbit review runs after implementation and verification.

## Acceptance Criteria

1. A patient or Hoon Buddy can create a persistent cloud case.
2. Missing details trigger follow-up questions.
3. The system creates ranked donor circles and an escalation plan.
4. Simulation mode runs the entire workflow without external messages.
5. Real email outreach cannot occur without admin approval.
6. Donor responses update the workflow and suppress unnecessary follow-ups.
7. Non-response advances follow-up and escalation automatically.
8. Coordinators can confirm arrival and close a case.
9. Refreshing or using another browser shows the same cloud state.
10. Every transition and outbound attempt has an auditable event.
