# Carbon Copy

**Living digital twin and intelligent blood coordination: a demonstration prototype.**

> Carbon Copy is a functional prototype built for demonstration. It uses **synthetic data only**, makes
> **no medical decisions**, and is **not clinically validated**.

Carbon Copy coordinates donors for patients who need recurring transfusions through a closed loop:

```
Patient Requirement → Living Digital Twin → Donor State Intelligence → Adaptive Cascade
  → Success | Failure → Failure Autopsy → Self-Healing Pathway → Learning
```

When an outreach attempt fails, the system analyses the failure and chooses an alternative pathway instead of
restarting the search. Deterministic rules make every operational decision. AI only explains, summarises and drafts.

## Repository

```
carbon-copy/
├── backend/            FastAPI + SQLAlchemy + SQLite API
├── frontend/           React + TypeScript + Vite + Tailwind UI
├── data/               Synthetic dataset seeds and generated output
├── docs/               Architecture and design documents
├── .env.example        Environment template (copy to .env)
└── docker-compose.yml  Optional containerised setup
```

## Quick start (Windows PowerShell)

Prerequisites: Python 3.12+ and Node.js 20.19+ (or 22.12+).

```powershell
# One-time: environment file
Copy-Item .env.example .env

# Terminal 1: backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m app.db.seed          # load the synthetic dataset (safe to re-run)
uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The status card should show **System Operational** and **Backend: Connected**, and
the Dataset status card should show 80 patients, 6,946 donors, 80 bridge groups, 320 requests and 7,240 interactions.

Alternatively, with Docker: `docker compose up --build`, then `docker compose exec backend python -m app.db.seed`.

## Synthetic dataset

> **Synthetic demonstration data — not for clinical use.** No real patient, donor, contact or medical information.

`python -m app.db.seed` (run from `backend/`) deletes existing data and regenerates the full dataset from the
fixed seed `20261008` in one transaction. The output is identical on every run. The demo scenario
`DEMO-REQUEST-001` (first donor does not respond → failure → recovery → second donor accepts) is always included.
See [Database architecture](docs/architecture.md#4-database-architecture-) for details.

Read-only API for checking the data: `/api/v1/system/dataset-stats`, `/api/v1/patients`, `/api/v1/donors`,
`/api/v1/bridge-groups`, `/api/v1/requests` (`?page=1&page_size=20`).

## Living Digital Twin

A computed view of each recurring patient's coordination state: cadence, current requirement, donor-network
strength, coordination history, recent activity, an operational state and a deterministic summary. Open
http://localhost:5173/patients/PAT-0001/digital-twin, or use the API:

- `GET /api/v1/patients/PAT-0001/digital-twin`
- `GET /api/v1/requests/DEMO-REQUEST-001/digital-twin-context`

It is deterministic, describes coordination state only (never medical health), and evaluates time as of the
dataset's reference time. See [Living Digital Twin Engine](docs/architecture.md#6-living-digital-twin-engine-).

## Donor State Intelligence

A deterministic, explainable assessment of each donor's coordination state: availability, demo coordination
eligibility (blood-group compatibility is a gate), reliability, response behaviour, coordination fatigue, contact
freshness and an operational priority with "why this donor?" reasons. Open
http://localhost:5173/donors/DON-00001?request=DEMO-REQUEST-001, or use the API:

- `GET /api/v1/donors/DON-00001/state`
- `GET /api/v1/donors/DON-00001/state-for-request/DEMO-REQUEST-001`
- `GET /api/v1/requests/DEMO-REQUEST-001/donor-comparison`

Operational ranking only, never a medical eligibility decision. See
[Donor State Intelligence Engine](docs/architecture.md#7-donor-state-intelligence-engine-).

## Matching Engine

Ranks the best candidate donors for a blood request: SQL candidate discovery (active, compatible, nearby), the
Donor State Engine's eligibility gate and assessment, then a deterministic match score (donor priority, request fit,
synthetic-coordinate distance, coordination context, urgency-aware exploration). Every excluded donor is reported
with its reason. Open http://localhost:5173/requests/DEMO-REQUEST-001/matching, or use the API:

- `GET /api/v1/requests/DEMO-REQUEST-001/matching?limit=10&include_excluded=true&evaluate_at=auto`

A coordination recommendation, not a medical one. See [Matching Engine](docs/architecture.md#8-matching-engine-).

## Adaptive Cascade (simulation)

Simulates wave-based outreach from the Matching Engine's ranking: wave 1 → simulated responses → Failure Autopsy →
Self-Healing (channel, wave size, bridge group, search radius, escalation) → re-matching → next wave,
until the requirement is secured or escalated. Deterministic and in memory: nothing is persisted and nobody is
contacted. Open http://localhost:5173/requests/DEMO-REQUEST-001/cascade?seed=25 (wave 1 fails, wave 2 secures
DON-00002), or use the API:

- `GET /api/v1/requests/DEMO-REQUEST-001/cascade?seed=25&response_stress=none`

See [Adaptive Cascade Engine](docs/architecture.md#9-adaptive-cascade-engine-simulation-).

## Failure Autopsy

A deterministic, evidence-based explanation of why a coordination attempt failed: failure type, severity,
rule confidence, evidence and a recommended action to consider — never a decision or a medical diagnosis.
**Autopsy recommends. Self-Healing decides. Learning remembers.** It analyses both RECORDED failures (what
actually happened in the synthetic dataset) and SIMULATED ones (embedded in each Adaptive Cascade wave),
always keeping the two separate. Visible on the same cascade page, between waves and in "What actually
happened": http://localhost:5173/requests/DEMO-REQUEST-001/cascade?seed=25. API:

- `GET /api/v1/requests/DEMO-REQUEST-001/failures/autopsy`
- `GET /api/v1/requests/DEMO-REQUEST-001/failures/{failure_code}/autopsy`

See [Failure Autopsy Engine](docs/architecture.md#10-failure-autopsy-engine-).

## Self-Healing

A deterministic recovery policy that answers **"what should change next?"** after a failed wave. **Failure
Autopsy: "What happened?" · Self-Healing: "What should change?" · Learning: "What should be remembered?"**
One documented first-match policy turns the autopsy and the cascade state into a recovery plan: a primary action
(switch channel, increase wave size, alternative donor or bridge group, expand search radius, re-run matching),
fallback actions, evidence, the exact changes and a hedged expected effect. Configurable limits (wave size,
radius, recovery attempts, channel switches, contacts) make automation stop at `HUMAN_COORDINATOR` or
`BLOOD_BANK_ESCALATION` with an explanation instead of retrying forever. The cascade applies the plan and
re-matches; nothing is persisted and nobody is contacted. See the plan on the cascade page
(http://localhost:5173/requests/DEMO-REQUEST-001/cascade?seed=25, or `REQ-00001?seed=2` for an SMS → CALL switch), or:

- `GET /api/v1/requests/DEMO-REQUEST-001/self-healing?seed=25`

Coordination recovery only, never a medical decision. See [Self-Healing Engine](docs/architecture.md#11-self-healing-engine-).

## Learning

A deterministic, descriptive analysis of coordination outcomes: **what should be remembered?** It compares
channel reply and acceptance rates, recurring failure patterns, what followed each recovery action, donor
contact load and coordination bottlenecks, and labels every insight with its numerator, denominator, sample size,
time window, **evidence strength** (`INSUFFICIENT_DATA` < 10 ≤ `LOW` < 30 ≤ `MODERATE` < 100 ≤ `HIGH`, observational
findings capped at `MODERATE`), reasoning and limits. **RECORDED** (stored data) and **SIMULATED** (cascade runs)
results are never mixed. Findings are associations, never causal claims, and recommendations are advisory:
nothing changes matching, donor state, recovery or safety limits. Bounded adjustment proposals appear only when
`LEARNING_ADJUSTMENTS_ENABLED=true` and are still not applied. Open http://localhost:5173/learning, or use the API:

- `GET /api/v1/learning/report`
- `GET /api/v1/requests/DEMO-REQUEST-001/learning?seed=25&runs=5`

Synthetic demonstration data, so results describe the generated dataset, not the real world. See
[Learning Engine](docs/architecture.md#12-learning-engine-).

## Notifications (foundation, Phase 10A)

A persistent notification record plus a REST API: create, list (pagination and filters),
fetch, summary counts and in-app read state, with idempotency keys to stop duplicate event notifications.
**Nothing is sent.** Every notification is `mode: DEMO` with status `SIMULATED` (or `QUEUED`); `SENT` and
`DELIVERED` are impossible for demo notifications (the database refuses them), and a successful response is not
evidence of delivery. There is no SMS, no WhatsApp and no Notification Center yet.

- `GET /api/v1/notifications`, `GET /api/v1/notifications/summary`, `GET /api/v1/notifications/{id}`
- `POST /api/v1/notifications`, `PATCH /api/v1/notifications/{id}/read`

**Demo-only and not production-secure: the API has no authentication.** The new `notifications` table is created
automatically at startup (`create_all` adds missing tables only); existing data is untouched and a reseed keeps
notifications. See [Notification foundation](docs/architecture.md#13-notification-foundation--phase-10a).

### Demo messaging provider (Phase 10B)

A small provider interface with one implementation, the **demo provider**, which records every message as
`DEMO` / `SIMULATED` through the notification service: no network, no provider message id, never `SENT` or
`DELIVERED`. `POST /api/v1/requests/{request_code}/cascade/notifications?seed=25` runs the same deterministic
simulation as the cascade page and records its events: donor outreach, wave failures, the Self-Healing recovery
decision, human-coordinator or blood-bank escalation, and the secured outcome (plus generic patient status
updates). It is explicit and idempotent (a simulation id derived from every parameter is part of each
idempotency key), and viewing any report never creates a notification. The cascade is a simulation, so these
notifications say so and imply no real contact. Not built yet: live SMS. See
[Demo messaging provider](docs/architecture.md#14-demo-messaging-provider--phase-10b).

### Notification Center (Phase 10C)

Open http://localhost:5173/notifications: summary cards, a paginated inbox with filters (recipient role, status,
channel, request code, unread only), expandable details, mark-as-read, and a clearly labelled demo action that
runs a deterministic cascade simulation for a request you find by code (search box backed by
`GET /api/v1/requests?search=`, starting on `DEMO-REQUEST-001`) and records its simulated notifications (never on page
load; repeats report "nothing new"; a simulation's notifications are stored all-or-nothing, so a failure leaves no partial set). Every notification is shown as DEMO / SIMULATED: no real SMS, WhatsApp
message or phone notification is sent, and the "sent or delivered" card is derived from the backend counts. See
[Notification Center](docs/architecture.md#147-notification-center-phase-10c).

### Live SMS (Phase 10E.1, controlled test only)

DEMO stays the default (`MESSAGING_MODE=DEMO`) and sends nothing. Setting `MESSAGING_MODE=LIVE` with `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN` and `TWILIO_FROM_NUMBER` in `backend/.env` (git-ignored; `.env.example` holds empty placeholders only)
enables **one explicitly authorised test SMS** via `POST /api/v1/notifications/test-sms`. It is refused unless the
recipient is a registered test recipient with recorded consent, verified, not opted out, and the message is an approved
template; synthetic donors and patients can never be recipients, and no page or report ever sends anything. Register
recipients with `python -m app.db.test_recipients add ...` (an operator action, deliberately not an API). `SENT` means the
provider accepted the request, **not** that it was delivered (there is no delivery tracking); timeouts are recorded as
`UNCERTAIN` and never resent. There is still no authentication, and Indian SMS regulation (DLT registration, templates,
consent) must be checked before anything beyond a controlled test. Automated tests use a mocked client and never call
Twilio. See [Live SMS provider](docs/architecture.md#15-live-sms-provider--phase-10e1).

## Checks

```powershell
cd backend;  pytest
cd frontend; npm run build
```

## Documentation

- [Demo runbook](docs/demo-runbook.md): verified jury walkthrough, exact startup commands, offline behaviour, limitations
- [Architecture](docs/architecture.md): product loop, layers, engine interfaces, data flow, demo scenario
- [Backend](backend/README.md)
- [Data](data/README.md)
