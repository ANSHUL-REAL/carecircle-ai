# AWS Hoon Buddy Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hoon Buddy an authenticated AWS-native conversational agent that reads patient context, remembers previous interactions, creates blood requests, and starts deterministic donor outreach.

**Architecture:** Amazon Bedrock generates natural responses and structured action intents. AWS Lambda validates the signed CareCircle token, reads DynamoDB patient/case/memory records, and returns grounded responses. The existing Python automation service remains the only component allowed to create cases, rank donors, and send or simulate donor applications.

**Tech Stack:** Amazon Bedrock Nova, AWS Lambda, DynamoDB, FastAPI, Docker, CloudFront, browser speech capture.

---

### Task 1: Authenticated Bedrock context

**Files:**
- Modify: `aws-ai-lambda/index.js`
- Create: `aws-ai-lambda/context.js`
- Test: `aws-ai-lambda/context.test.js`

- [ ] Validate the bearer token with the shared `AUTH_SECRET`.
- [ ] Load the authenticated user from `CareCircleUsers`.
- [ ] Load only cases owned by the authenticated patient.
- [ ] Reject attempts to supply another patient's identity from the browser.

### Task 2: Persistent conversation memory

**Files:**
- Modify: `aws-ai-lambda/index.js`
- Create: `aws-ai-lambda/memory.js`
- Test: `aws-ai-lambda/memory.test.js`

- [ ] Store compact user/assistant turns in `CareCircleConversationMemory`.
- [ ] Retrieve the latest relevant turns for the authenticated user.
- [ ] Keep medical facts grounded in database records rather than treating memory as authoritative.

### Task 3: Deterministic action tools

**Files:**
- Modify: `aws-ai-lambda/assistant.js`
- Modify: `app.js`
- Test: `aws-ai-lambda/assistant.test.js`
- Test: `hoon-action.test.js`

- [ ] Return structured intents for profile lookup, case status, blood request creation, and donor outreach.
- [ ] Require explicit patient confirmation before creating a case.
- [ ] Send confirmed actions to the existing automation API.
- [ ] Let the automation service perform compatibility, ranking, and outreach decisions.

### Task 4: AWS deployment

**Files:**
- Modify: AWS Lambda package and configuration
- Modify: IAM policies
- Create: DynamoDB memory table

- [ ] Create the memory table with on-demand billing.
- [ ] Grant the AI Lambda least-privilege DynamoDB access.
- [ ] Deploy the AI Lambda package and environment variables.
- [ ] Deploy the updated frontend Docker image.

### Task 5: Verification

- [ ] Log in as a patient and ask for profile information.
- [ ] Ask for the latest blood-request status.
- [ ] Create a request through a multi-turn voice conversation.
- [ ] Confirm that the cloud case is created only after approval.
- [ ] Confirm subsequent conversations use stored interaction memory.
