# CareCircle AI v2

## Predictive Blood Support & Care Coordination Platform

## Problem Statement

Blood donation platforms focus on finding donors after an emergency occurs.

However, many patients such as Thalassemia, Sickle Cell Disease, Cancer, Dialysis, and Surgery patients require recurring blood support.

Today the process is mostly manual:

* Families search for donors through WhatsApp groups.
* Volunteers repeatedly call donors.
* Donor confirmations are uncertain.
* Backup plans are often missing.
* Blood Warriors become overloaded.
* Hospitals have limited visibility into donor coordination.

The problem is not only blood shortage.

The problem is coordination failure.

---

# Vision

Transform blood support from reactive emergency response into proactive care coordination.

Instead of searching for blood when a crisis begins, CareCircle AI predicts future needs, prepares donor circles, coordinates volunteers, and escalates support automatically.

---

# Core Users

## Patients & Families

Need blood support for recurring or emergency cases.

## Donors

Want to donate blood and receive relevant requests.

## Volunteers

Coordinate donors and patient requests.

## Blood Warriors

Manage large-scale coordination efforts.

## NGOs & Blood Banks

Provide blood inventory and emergency support.

---

# Unique Value Proposition

Most platforms answer:

"Who can donate right now?"

CareCircle AI answers:

"Who will need blood soon and how can we prepare before it becomes an emergency?"

---

# Core Features

## 1. Patient Blood Request

Patient enters:

* Name
* Blood Group
* Hospital
* Location
* Disease Type
* Last Transfusion Date
* Required Date
* Urgency

System creates a request.

---

## 2. Recurring Blood Need Prediction

For recurring patients:

* Thalassemia
* Sickle Cell
* Cancer Treatments
* Chronic Conditions

AI predicts:

* Next likely transfusion date
* Risk score
* Preparation timeline

Example:

Last transfusion: May 1

Typical cycle: 21 days

Prediction:

Next need: May 22

Preparation starts: May 10

---

## 3. Blood Risk Score

AI generates:

0-100 risk score

Factors:

* Blood group rarity
* Donor availability
* Time remaining
* Location
* Historical response rate

Example:

92/100

Critical Risk

Reason:
Rare blood group + low donor availability + transfusion in 2 days

---

## 4. AI Donor Ranking Engine

Instead of random donor lists.

Ranking Factors:

* Blood group compatibility
* Distance
* Eligibility
* Last donation date
* Response history
* Availability
* Donor fatigue

Output:

* Primary donor
* Backup donor
* Nearby donor
* Emergency donor

---

## 5. Donor Circle Generation

Instead of finding one donor.

Generate:

* Primary Circle
* Backup Circle
* Emergency Circle

This increases success probability.

---

## 6. Volunteer Dashboard

Shows:

* Assigned tasks
* Pending confirmations
* Escalations
* Priority requests
* Donor response status

Features:

* Follow-up reminders
* Escalation alerts
* Request tracking

---

## 7. Family Status Tracker

Families can track:

✓ Request Created

✓ Volunteer Assigned

✓ Donor Contacted

✓ Donor Confirmed

✓ Backup Ready

✓ Blood Available

✓ Completed

Reduces uncertainty.

---

## 8. Emergency Escalation Engine

If donor does not respond:

Step 1:
Activate Backup Donors

Step 2:
Notify Volunteers

Step 3:
Suggest Nearby Blood Banks

Step 4:
Escalate to Coordinator

System never depends on one donor.

---

## 9. Blood Bank Discovery

Uses real blood bank datasets.

Shows:

* Nearby blood banks
* Contact information
* Location
* Available support

---

## 10. Blood Warrior Command Center

Central dashboard showing:

* Active Requests
* High Risk Cases
* Donor Activity
* Volunteer Activity
* Escalated Requests

---

# Bonus Winning Features

## Blood Passport

Every donor receives:

* Blood Group
* Donations Count
* Lives Impacted
* Last Donation Date
* Eligible Again Date

Gamified donor profile.

---

## City Blood Heatmap

Visual map showing:

* High demand zones
* Low donor availability zones
* Upcoming recurring patient needs

Useful for NGOs and Blood Warriors.

---

# MVP Scope

Build only:

* Authentication
* Patient Request Form
* AI Risk Score
* Donor Ranking
* Donor Circle
* Volunteer Dashboard
* Family Tracking
* Blood Bank Directory

Skip:

* WhatsApp Integration
* SMS Integration
* Hospital Integration

These can be mocked.

---

# Tech Stack

Frontend:

* Next.js
* Tailwind CSS
* Shadcn UI

Backend:

* FastAPI

Database:

* Supabase PostgreSQL

Authentication:

* Supabase Auth

Maps:

* Mapbox

AI:

* Amazon Bedrock

Hosting:

* Vercel
* Render

---

# Architecture

Users
↓
Next.js Frontend
↓
FastAPI Backend
↓
Supabase Database
↓
AI Risk Engine
↓
Donor Ranking Engine
↓
Notification Service
↓
Analytics Dashboard

---

# Why This Can Win

1. Solves a real social problem.
2. Uses AI for prediction, not just matching.
3. Helps Blood Warriors directly.
4. Creates backup planning.
5. Supports recurring care.
6. Scales city-wide.
7. Has clear real-world deployment potential.

CareCircle AI is not a donor finder.

It is an Operating System for Blood Support Coordination.
