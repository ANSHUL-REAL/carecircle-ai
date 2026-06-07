# CareCircle AI: Demo and Technical Guide

## One-Line Explanation

CareCircle AI converts a blood requirement into a tracked cloud case, ranks
compatible donors, follows up automatically, escalates when donors do not
respond, and keeps a human coordinator in control of final fulfillment.

## The Problem

Blood coordination is often handled through phone calls and WhatsApp groups.
The process is slow, repeated manually, difficult to audit, and dependent on
someone remembering whom to contact next. CareCircle turns that process into a
stateful workflow.

## Architecture

```text
Browser
  |-- HTML/CSS/JavaScript user interface
  |-- Browser speech recognition and speech synthesis
  |
  |-- Auth API Gateway -> Auth Lambda -> DynamoDB Users
  |-- AI API Gateway -> AI Lambda -> Amazon Bedrock Nova Micro
  |                                  -> S3 extraction records
  |-- Automation API Gateway -> Python FastAPI Lambda
                                   |-- DynamoDB cases
                                   |-- DynamoDB donors and donor memory
                                   |-- DynamoDB events, approvals, attempts, tasks
                                   |-- SES or SNS messaging adapters
                                   |-- EventBridge schedule every 15 minutes
```

## Main AWS Services

1. **Amazon Bedrock**
   Runs Hoon Buddy using Amazon Nova Micro. It understands natural-language
   requests, asks follow-up questions, and returns structured action data.

2. **AWS Lambda**
   Separate serverless functions handle authentication, Bedrock requests, and
   Python workflow automation.

3. **Amazon API Gateway**
   Provides HTTPS endpoints used by the website.

4. **Amazon DynamoDB**
   Stores users, blood cases, donors, donor memory, event history, outreach
   attempts, approvals, and escalation tasks.

5. **Amazon EventBridge**
   invokes the automation Lambda every 15 minutes.

6. **Amazon S3**
   stores structured extractions made from hospital notes or messages.

7. **Amazon SES and SNS**
   are the supported email and SMS delivery adapters. The current deployment is
   in simulation mode until sender identities and production messaging access
   are configured.

## How Hoon Buddy Works

Example command:

> I need two units of B positive blood in Delhi this week.

1. The browser converts microphone audio to text using the Web Speech API.
2. The request goes through API Gateway to the AI Lambda.
3. The Lambda sends a constrained prompt to Bedrock Nova Micro.
4. Bedrock returns an answer, intent, and structured request draft.
5. A deterministic validation layer normalizes values such as `B positive` to
   `B+`, limits units, and converts deadlines to `YYYY-MM-DD`.
6. Known information is kept across turns.
7. Hoon Buddy asks one follow-up question for missing required information,
   such as the hospital.
8. When the request is complete, CareCircle shows a confirmation summary.
9. After confirmation, the authenticated patient's cloud case is created.

Bedrock proposes and extracts information. Deterministic code validates the
payload before any workflow action is allowed.

## Automation Workflow

```text
New blood requirement
        |
Request intelligence
Extracts patient, blood group, units, hospital, city, deadline, urgency
        |
Decision intelligence
Ranks compatible and eligible donors
        |
Donor outreach
Creates initial outreach attempts
        |
Response understanding
Records accepted, declined, unavailable, opt-out, or unclear responses
        |
Follow-up
Retries non-responsive donors up to three attempts
        |
Escalation
Creates volunteer, blood-bank, and Blood Warrior tasks
        |
Coordination
Moves confirmed cases into coordination
        |
Memory
Updates donor fatigue, response history, opt-out, and next eligibility
        |
Human-confirmed closure
Coordinator marks the case fulfilled or cancelled
```

## Case State Machine

Typical states are:

`DRAFT -> PLANNED -> OUTREACH_ACTIVE -> DONOR_CONFIRMED -> COORDINATING -> FULFILLED`

Other controlled outcomes include:

- `NEEDS_INFORMATION`
- `AWAITING_APPROVAL`
- `CANCELLED`
- `EXPIRED`
- `UNFULFILLED`

Invalid state transitions are rejected by the API.

## Donor Ranking

The ranking engine considers:

- Blood compatibility
- City
- Eligibility
- Reliability
- Donor fatigue
- Opt-out status
- Previous donor memory
- Number of units required

The system contacts a primary circle first and creates escalation work when the
primary circle cannot satisfy the request.

## Authentication and Security

- Passwords are salted and hashed with PBKDF2 before DynamoDB storage.
- Passwords are never returned to the browser.
- Signed session tokens contain role, email, linked ID, and expiry.
- Sessions persist through refresh using browser local storage.
- The automation API verifies token signatures and role permissions.
- Patients can only list and view their own cases.
- Admin and volunteer roles control planning and coordination operations.
- Public signup only permits patient and donor roles.
- Provider credentials are not stored in frontend JavaScript.
- Deployment keys and generated archives are excluded by `.gitignore`.

## Safety Decisions

- The LLM does not directly mark a case fulfilled.
- A user confirms a structured request before it is created.
- Final transfusion completion remains human-confirmed.
- Hoon Buddy does not diagnose or replace a clinician.
- Real outreach is separated behind SES/SNS adapters.
- The scheduler processes at most 25 active cases per run.
- The website clearly displays simulation mode.

## Current Deployment Status

- Bedrock assistant: live
- Structured Bedrock extraction: live and stored in S3
- Authentication: live in DynamoDB
- Python automation API: live
- EventBridge schedule: enabled every 15 minutes
- Case listing and idempotency filtering: fixed and live
- Scheduled follow-up and escalation: live
- Real donor email/SMS: simulation mode

Real messages require verified SES sender identities or SNS configuration. Do
not claim that real donors are currently receiving messages.

## Suggested Demo

1. Open Hoon Buddy.
2. Say or type: `I need two units of B positive blood in Delhi this week.`
3. Show that Hoon Buddy understands `B positive` as `B+`.
4. Answer its hospital question.
5. Show the final request confirmation.
6. Sign in as a patient and create the case.
7. Open the admin dashboard and show the case and state.
8. Explain that EventBridge wakes the Python agent every 15 minutes.
9. Show the outreach, follow-up, and escalation timeline.
10. Demonstrate Bedrock Data Extraction with a hospital note.

## Useful Answers for Judges

**Is this only a chatbot?**

No. The chatbot is the input layer. The main system is a Python state machine,
ranking engine, event log, scheduled follow-up worker, and escalation workflow.

**Does the LLM control medical decisions?**

No. Bedrock extracts intent and fields. Validation, blood compatibility,
permissions, state transitions, retry limits, and case closure are handled by
deterministic code.

**How is it autonomous?**

After case creation, EventBridge invokes the scheduler every 15 minutes. The
scheduler plans new cases, starts outreach, follows up, escalates, expires old
requests, and moves confirmed cases into coordination.

**Why keep a human in the loop?**

Blood availability and transfusion completion are safety-critical. Automation
reduces delay, while a coordinator confirms the real-world outcome.

**How do you prevent repeated duplicate requests?**

Case creation requires an idempotency key. The key and request hash are stored
transactionally with the case and creation event.

**How do you handle donor fatigue?**

Donor memory tracks contact history, responses, opt-out status, fatigue, and
the next eligible donation date. Ranking and outreach skip ineligible or
opted-out donors.

**What costs money?**

The application code and libraries are free/open source. AWS usage is billable.
Bedrock is the main variable AI cost; Lambda, DynamoDB, EventBridge, S3, SES,
and SNS depend on usage. The scheduler and request limits bound accidental
usage, but AWS Billing Budgets should still be enabled.

## Verification Results

- Python tests: `306 passed`
- Hoon Buddy and auth regression tests: `10 passed`
- JavaScript syntax checks: passed
- Live Bedrock assistant request: passed
- Live two-turn follow-up request: passed
- Live Bedrock extraction and S3 storage: passed
- Live authenticated case listing: passed
- Live EventBridge-style scheduler invocation: passed
- Browser Hoon Buddy typed command: passed

The browser microphone itself depends on Chrome/Edge microphone permission and
the browser's Web Speech API. Typed commands provide a fallback.
