# Carbon Copy — Architecture

> **Prototype notice.** Carbon Copy is a functional demonstration prototype built for a jury presentation.
> It runs on synthetic data only, makes no medical decisions and is not clinically validated.
> Any "eligibility" or "compatibility" logic in this system is a simplified, configurable demo rule set,
> not clinical guidance.

Status legend used below: **✅ built** · **🗺️ planned** (interface documented, not implemented).

---

## 1. Product architecture

Carbon Copy coordinates blood donors for patients who need **recurring** transfusions. Its distinguishing idea is a
**closed loop**: a failed outreach attempt is not simply retried. It is analysed, and the analysis selects a different
coordination pathway.

```
 Patient Requirement
        │
        ▼
 Living Digital Twin  ◄──────────────────────────────┐
        │                                            │
        ▼                                            │
 Donor State Intelligence                            │
        │                                            │
        ▼                                            │
 Adaptive Cascade ──► Outcome ──► Success ──► Learning
        ▲                │                           ▲
        │             Failure                        │
        │                ▼                           │
        │         Failure Autopsy                    │
        │                │                           │
        │                ▼                           │
        └──────── Self-Healing Pathway ──────────────┘
```

| Concept | What it is |
|---|---|
| **Living Digital Twin** | A dynamic model of one recurring patient's coordination needs: cadence, requirements, bridge group, history of what has and hasn't worked. More than a static record — it is updated by every outcome. |
| **Donor State Intelligence** | A per-donor state combining availability, (demo-rule) eligibility, reliability and fatigue, used to prioritise donors. |
| **Adaptive Cascade** | Ordered, wave-based outreach to suitable donors that changes pathway when an attempt fails. |
| **Failure Autopsy** | Turns an unsuccessful attempt into a structured failure report (category, contributing factors, evidence). |
| **Self-Healing Pathway** | Uses the failure report to choose an alternative route (different donors, channel, radius, or escalation). |
| **Learning** | Records outcomes as structured events that adjust future donor scoring and twin parameters. |

### Decision boundary: rules decide, AI explains

| Deterministic services (decide) | AI layer (assist, never decide) |
|---|---|
| Compatibility, distance, availability, eligibility, reliability, fatigue, donor prioritisation, cascade progression, failure classification, recovery-pathway selection | Explanations of rankings, narrative failure analysis, natural-language summaries, coordinator Q&A, outreach message drafts |

The AI layer receives the deterministic results as read-only context. Its output is advisory text for a human
coordinator and is never fed back as an operational decision. **An LLM must never make or override a medical
eligibility decision.** The application must remain fully functional with AI disabled.

---

## 2. Frontend architecture ✅

React 19 + TypeScript + Vite, styled with Tailwind CSS v4, icons from Lucide, routing with React Router.
Recharts is used only on the Digital Twin page. The twin, donor state, matching and cascade pages are lazy-loaded.

```
frontend/src/
├── App.tsx              Route table (createBrowserRouter)
├── main.tsx             Entry point
├── index.css            Tailwind import + design tokens (@theme)
├── layouts/             Page chrome. AppLayout owns the health poll and shares it via <Outlet context>
├── pages/               One component per route (Overview, Patients, DigitalTwin, Donors, DonorState, Matching, Cascade, Learning, NotFound) —
  Failure Autopsy has no page of its own; it renders inside the Cascade page
├── components/
│   ├── ui/              Design-system primitives (Card, StatusBadge, StatusDot)
│   ├── system/          System status widgets
│   ├── overview/        Overview page sections
│   ├── twin/            Digital Twin cards, timeline and chart
│   ├── donor/           Donor state cards and the reusable DonorComparisonTable
│   ├── matching/        Ranking table, "Why #k?" card, excluded-candidates section
│   └── cascade/         Wave cards, FailureAutopsyPanel and the self-healing connector
├── services/            HTTP layer: apiClient (fetch, timeout, ApiError) + one module per backend area
├── hooks/               Stateful logic (useSystemHealth, useDatasetStats, useApiQuery)
├── types/               TypeScript mirrors of backend Pydantic schemas
└── lib/                 Config and small utilities
```

Rules:
- Components never call `fetch` directly; they go through `services/`.
- `types/api.ts` mirrors `backend/app/schemas/`. When a schema changes, update both (OpenAPI codegen can replace this later).
- Configuration comes from `VITE_*` variables in the repository-root `.env` (`envDir: ".."`).
- Visual direction: light, high-contrast, projector-friendly; slate neutrals, a single crimson brand accent,
  semantic status colours (emerald/amber/red), minimal animation.

---

## 3. Backend architecture ✅

FastAPI + Pydantic v2 + SQLAlchemy 2, layered so each piece can be tested in isolation.

```
backend/app/
├── main.py           create_app() factory: CORS, routers, lifespan (init_db)
├── core/config.py    Settings (pydantic-settings), env + .env loading
├── api/
│   ├── deps.py       Dependency providers (settings, DB session, AI provider, services)
│   ├── router.py     Versioned router mounted at /api/v1
│   └── routes/       Thin HTTP handlers: parse → call service → return schema
├── schemas/          Pydantic request/response models (API boundary)
├── services/         Business logic. No FastAPI imports, no HTTP concerns
├── repositories/     Query code (SQLAlchemy selects); services never build queries themselves
├── models/           SQLAlchemy ORM models + enums
├── db/               Engine, session factory, Base, column types, synthetic generator + seed command
└── ai/               AIProvider interface + implementations (isolated)
```

Request path: `route → Depends(get_x_service) → service → repository → models → schema`.

Current endpoints (all read-only):

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + DB connectivity: `{"status":"ok","service":"carbon-copy-api",...}` |
| GET | `/api/v1/system/status` | Environment, DB state, AI provider state, demo disclaimer |
| GET | `/api/v1/system/dataset-stats` | Row counts for every table, `seeded` flag, data notice |
| GET | `/api/v1/patients` | Paginated patients |
| GET | `/api/v1/donors` | Paginated donors, each with its `state_snapshot` |
| GET | `/api/v1/bridge-groups` | Paginated bridge groups |
| GET | `/api/v1/requests` | Paginated blood requests. Optional `search` (1-24 characters) finds requests whose code contains the text, case-insensitive, exact match first, `%` and `_` treated literally |
| GET | `/api/v1/patients/{patient_code}/digital-twin` | Living Digital Twin (section 6) |
| GET | `/api/v1/requests/{request_code}/digital-twin-context` | Request context + patient twin (section 6) |
| GET | `/api/v1/donors/{donor_code}/state` | Donor State assessment (section 7) |
| GET | `/api/v1/donors/{donor_code}/state-for-request/{request_code}` | Donor assessed for a request (section 7) |
| GET | `/api/v1/requests/{request_code}/donor-comparison` | Compare listed donors for a request (section 7) |
| GET | `/api/v1/requests/{request_code}/matching` | Ranked, explained candidate list (section 8) |
| GET | `/api/v1/requests/{request_code}/cascade` | Simulated adaptive cascade (section 9) |
| POST | `/api/v1/notifications/test-sms` | One controlled live test SMS to a registered, consenting test recipient (section 15); refused in DEMO mode |
| POST | `/api/v1/requests/{request_code}/cascade/notifications` | Record a simulation's events as DEMO notifications (section 14) |
| GET / POST | `/api/v1/notifications` | List (filters, pagination) / record a DEMO notification (section 13) |
| GET | `/api/v1/notifications/summary` | Notification counts by status, mode and channel (section 13) |
| GET / PATCH | `/api/v1/notifications/{id}` , `/{id}/read` | One notification / mark an in-app notification read (section 13) |
| GET | `/api/v1/learning/report` | RECORDED learning insights (section 12) |
| GET | `/api/v1/requests/{request_code}/learning` | SIMULATED learning insights for pooled cascade runs (section 12) |
| GET | `/api/v1/requests/{request_code}/self-healing` | Recovery plans of the simulated cascade (section 11) |
| GET | `/api/v1/requests/{request_code}/failures/autopsy` | Recorded Failure Autopsy for a request (section 10) |
| GET | `/api/v1/requests/{request_code}/failures/{failure_code}/autopsy` | Recorded Failure Autopsy for one failure (section 10) |
| GET | `/docs` | Interactive OpenAPI documentation (`/` redirects here) |

List endpoints take `?page=1&page_size=20` (`page_size` ≤ 100) and return
`{"items": [...], "page", "page_size", "total", "pages"}`. Records are identified by public codes
(`PAT-0001`, `DON-00001`, …); internal database ids are not exposed. No filtering yet.

Conventions:
- Route handlers contain no business logic.
- Services receive their collaborators through constructors (wired in `api/deps.py`), so tests can pass fakes.
- `/health` is unversioned; all feature endpoints live under `/api/v1/<area>`.

---

## 4. Database architecture ✅

> **Synthetic demonstration data — not for clinical use.** Every record is fabricated by a seeded generator.
> No real names, phone numbers, addresses or medical records exist anywhere in the dataset.

SQLite via SQLAlchemy 2. `db/base.py` defines `Base` with a deterministic constraint naming convention;
`db/session.py` builds the engine (foreign keys enforced) and the per-request session; `db/types.py` stores enums
as plain strings (`enum_column`). All datetimes are naive UTC. Relative SQLite paths resolve against `backend/`.
Tables are created by `init_db()` (`create_all`); Alembic will be introduced when the schema stabilises.

### Entity diagram

```
 Patient ──N:1──► BridgeGroup ◄──N:1── Donor ──1:1──► DonorState
    │                  ▲  ▲               ▲  ▲  ▲
   1:N                 │  │               │  │  │
    ▼                  │  │               │  │  │
 BloodRequest ──N:1────┘  │               │  │  │
    │                     │               │  │  │
    ├──1:N──► DonorInteraction ──N:1──────┘  │  │     (optional N:1 → CoordinationAttempt)
    │                     │                  │  │
    ├──1:N──► CoordinationAttempt ──N:1──────┘  │
    │             └──1:1──► Failure             │
    │                         └──1:N──► RecoveryAction ──► target Donor / target BridgeGroup (optional)
    │
    └──1:N──► LearningEvent ──N:1──► Donor (optional)
```

### Entities

| Table | Model | Responsibility |
|---|---|---|
| `patients` | `Patient` | Recurring patient: blood group, urgency, transfusion cadence, last/next requirement, home bridge group. Input to the future Digital Twin. |
| `bridge_groups` | `BridgeGroup` | Fictional NGO / volunteer network / caregiver group / community group supporting a patient. Escalation target. |
| `donors` | `Donor` | Donor profile: blood group, location (synthetic coordinates), placeholder phone, optional bridge-group affiliation. |
| `donor_states` | `DonorState` | Seeded baseline snapshot. Its registry fields (declared availability, deferral flag, donation record) are inputs to the Donor State Engine; its placeholder scores are not used. The engine's computed assessment is authoritative (section 7). |
| `blood_requests` | `BloodRequest` | A dated requirement for one patient. Status flow `OPEN → MATCHING → COORDINATING → (RECOVERING) → FULFILLED`, or `CANCELLED`. |
| `donor_interactions` | `DonorInteraction` | One simulated message or call (`AVAILABILITY_CHECK`, `DONATION_REQUEST`, `FOLLOW_UP`, `CONFIRMATION`) and its response. Linked to an attempt when part of one; broadcast checks are not. |
| `coordination_attempts` | `CoordinationAttempt` | One cascade step committing to a specific donor, with `sequence_number` and a `priority_score` that strictly decreases within a request. |
| `failures` | `Failure` | Structured analysis of one failed attempt: category, severity, recommended action, `analyzed` flag. |
| `recovery_actions` | `RecoveryAction` | The alternative pathway chosen after a failure (next/alternative donor, bridge-group escalation, expanded search, blood-bank referral, coordinator review). |
| `learning_events` | `LearningEvent` | Signed signal in [-1, 1] derived from an attempt or recovery outcome, traceable through `source_reference`. |

Controlled values are Python `StrEnum`s in `app/models/enums.py`: `BloodGroup`, `UrgencyLevel`, `RequestStatus`,
`AvailabilityStatus`, `EligibilityStatus`, `InteractionResponseStatus`, `CoordinationStatus`, `CoordinationOutcome`,
`FailureCategory`, `RecoveryActionType`, plus a few supporting enums.

### Relationships and delete behaviour

- **Ownership cascades** (ORM `delete-orphan` + DB `ON DELETE CASCADE`): Patient → BloodRequest → {DonorInteraction,
  CoordinationAttempt, LearningEvent}; CoordinationAttempt → Failure → RecoveryAction; Donor → DonorState.
- **History is protected**: interactions and attempts reference donors with `ON DELETE RESTRICT`.
- **Optional references** use `ON DELETE SET NULL` (bridge groups, recovery target donor, learning-event donor,
  interaction → attempt).
- `BloodRequest.recovery_actions` is a read-only shortcut; recovery actions are owned through their failure.
  There are no relationship cycles.

### Synthetic data strategy

The generator (`app/db/synthetic.py`) is a pure function, `generate_dataset(seed) → rows`. It **simulates**
coordination instead of sampling each table independently, so every record has a cause:

1. 80 bridge groups and 80 patients (one home group each) across 12 Telangana locations.
2. 6,946 donors with a realistic blood-group mix (O+ 33 %, B+ 31 %, A+ 21 %, AB+ 8 %, negatives 7 %),
   coordinates jittered around city centres, ~45 % affiliated with a local bridge group, ~93 % active.
3. 4 requests per patient (320): three past cycles at the patient's transfusion cadence plus the current one.
   Current requests cover every status (OPEN, MATCHING, COORDINATING, RECOVERING, FULFILLED, CANCELLED).
4. For each request, in chronological order: broadcast availability checks to compatible donors → a cascade of
   attempts (0–3 failures before success, per unit) → a `Failure` and a `RecoveryAction` for each failed attempt
   → the next attempt follows that recovery (bridge-group escalation picks an affiliated donor; an alternative
   donor is called instead of messaged) → `LearningEvent`s for each completed attempt and each resolved recovery.
5. Demo rules keep it coherent: simplified ABO/Rh compatibility, a 90-day interval between one donor's
   donations, and less responsive donors are more likely to be the ones who do not reply.
6. `DonorState` is derived from each donor's latent traits plus their simulated history (recent contacts raise
   fatigue; a recent donation makes the donor `TEMPORARILY_DEFERRED`). `current_priority_score` is a placeholder
   until the Donor State Engine exists.
7. Broadcast checks are sized so interactions total exactly 7,240. The latest events of current requests are
   anchored shortly before the dataset's reference time (`2026-10-08 09:00 UTC`); nothing happens after it.

These demo rules are **not clinical guidance**. Eligibility in this dataset is not a medical determination and
does not imply any real donor's eligibility.

Generated counts with the default seed `20261008`:

| Table | Rows |
|---|---|
| patients | 80 |
| bridge_groups | 80 |
| donors | 6,946 |
| donor_states | 6,946 |
| blood_requests | 320 |
| donor_interactions | 7,240 |
| coordination_attempts | 576 |
| failures | 266 |
| recovery_actions | 266 |
| learning_events | 799 |

### Seed command

From `backend/` with the virtual environment active:

```powershell
python -m app.db.seed            # default seed 20261008
python -m app.db.seed --seed 42  # a different, equally reproducible dataset
```

The command creates missing tables, deletes all existing rows and inserts the full dataset in one transaction
(under a second). Running it again produces identical data and never duplicates it.

## 5. AI orchestration architecture

**Today ✅:** `app/ai/` defines the seam.

```python
class AIProvider(ABC):
    name: str
    enabled: bool                                     # property
    async def generate(self, request: AIRequest) -> AIResult

AIRequest(task: AITask, context: dict, instructions: str | None)
AIResult(text: str, provider: str, generated: bool)  # generated=False → fallback, no model called
AITask = explain_prioritization | analyze_failure | summarize | draft_message | coordinator_assist
```

`build_ai_provider(settings)` returns `DisabledAIProvider` in every environment for now. Routes obtain the provider
through `Depends(get_ai_provider)`, so swapping implementations touches one function.

**Planned 🗺️:**
- `ClaudeAIProvider` selected when `CLAUDE_API_KEY` is set.
- An `AIAssistant` service with task-specific methods (e.g. `explain_ranking(candidates)`,
  `narrate_failure(report)`, `draft_outreach(donor, request)`) that builds prompts from deterministic engine output,
  validates the response, and falls back to template text when AI is disabled or fails.
- Every AI output is labelled as AI-generated in the UI, and stored alongside the deterministic facts it described.

---

## 6. Living Digital Twin Engine ✅

> **The current Digital Twin is deterministic and synthetic-data driven. AI-assisted reasoning will be added in a
> later stage.** It describes coordination and donor-network state only. It is not a medical assessment, and its
> states and scores carry no clinical meaning.

### 6.1 Purpose

Answer one question before any donor search starts: *what is this recurring patient's current coordination state,
and what should the system know first?* The twin is computed from existing records on every call (no extra table),
so it always reflects the latest data. Later engines consume it: Donor State, Matching, Adaptive Cascade, Failure
Autopsy and Self-Healing.

Code: `app/services/digital_twin.py` (rules + service), `app/services/digital_twin_summary.py` (summary),
`app/repositories/digital_twin_repository.py` (queries), `app/schemas/digital_twin.py` (response model).

### 6.2 Inputs

| Input | Source |
|---|---|
| Profile and cadence | `patients` (blood group, location, urgency, `transfusion_frequency_days`, last/next requirement) |
| Requests and outcomes | the patient's `blood_requests` → `coordination_attempts` → `failures` → `recovery_actions` |
| Outreach volume | `donor_interactions` for the patient's requests (counted in SQL) |
| Donor network | network donor ids from SQL, assessed in one batch by the Donor State Engine (see 6.4) |
| Clock | `app/core/clock.py`: the dataset reference time `2026-10-08 09:00 UTC` by default (`CLOCK_MODE=system` for real time), so demo results do not drift from day to day |

Performance: about 10 queries per twin; only the patient's network donors are loaded. A twin takes about
20–25 ms on the synthetic dataset, so no extra indexes were needed (the existing foreign-key indexes suffice).

### 6.3 Calculated outputs

```
DigitalTwinState
├── patient                 identity, location, urgency profile, bridge group
├── transfusion_profile     cadence, last / next requirement, days until, recurrence_status
├── requirement_state       active request? current request (active, or fulfilled one covering the next need),
│                           units, status, urgency, required_by, attempts so far, pending recovery
├── coordination_history    request counts by outcome, success rates, attempts, failures, recoveries,
│                           per-request outcome rows (used by the chart)
├── network_state           donor counts + network_strength_score (0–100), band and components
├── recent_activity         30-day window counts, last success / failure, timeline of the focus request
├── operational_state       HEALTHY | WATCH | ATTENTION | ACTIVE_COORDINATION, with reasons
└── summary                 deterministic text (summary_source = "deterministic")
```

Definitions worth knowing:
- **Active request**: status `OPEN`, `MATCHING`, `COORDINATING` or `RECOVERING`.
- **Requirement covered**: no active request, and a `FULFILLED` request whose `required_by` is still ahead of
  the clock, meaning a donor is already confirmed for the next need.
- **Historical success rate**: fulfilled ÷ (fulfilled + cancelled), as a whole percent. Active requests are excluded.
- **Requests with failures**: requests that had at least one failed attempt (most were still fulfilled).
- **Successful recoveries**: recovery actions whose target donor then accepted in the same request.
- **Recent window**: 30 days before the clock, for interactions, failures, successes and recent contacts.

### 6.4 Network strength calculation

The patient's **known network** is the union of donors already contacted for any of the patient's requests and
compatible members of the patient's bridge group (simplified ABO/Rh table in `app/core/blood.py`).

| Count | Rule |
|---|---|
| active | `donor.active` |
| available (reachable) | active, eligible (demo rules) and availability `AVAILABLE` or `RECENTLY_CONTACTED` |
| high reliability | active and Donor State reliability band HIGH (≥ 70) |
| fatigued | active and coordination fatigue band HIGH (≥ 60) |
| recently contacted | any simulated contact in the last 30 days |

All per-donor values come from the Donor State Engine (section 7). "Available" here means *reachable network
capacity*: a donor mid-outreach is still part of the network, even though the donor page shows them as recently
contacted.

```
network_strength_score = round(100 × (0.40·depth + 0.25·reliability + 0.15·responsiveness + 0.20·freshness))
  depth          = min(available ÷ 50, 1)            # 50 ≈ two broadcast waves of compatible donors
  reliability    = mean Donor State reliability score of available donors ÷ 100
  responsiveness = mean Donor State response score of available donors ÷ 100
  freshness      = 1 − fatigued ÷ active
bands: STRONG ≥ 75 · MODERATE 55–74 · WEAK < 55
```

The score is deterministic, bounded 0–100 and explainable: the API returns each component (0–100) and its weight,
and the UI shows them. The depth target and band cut-offs are **demo calibration** against the synthetic dataset
(a first target of 25 put every patient in STRONG). With the default seed and Donor State inputs: 65 STRONG,
13 MODERATE, 2 WEAK. PAT-0001 (B−) scores 56 MODERATE, held back by fatigue in its rare-group network.
This is not a clinical score.

### 6.5 Recurrence calculation

`days_until = next_expected_requirement − clock date`. The windows scale with each patient's own cadence and are
coordination lead-time windows, not medical thresholds:

| Status | Rule (21-day cadence in brackets) |
|---|---|
| UNKNOWN | no next date or no cadence |
| OVERDUE | days_until < 0 |
| DUE | days_until ≤ max(1, round(10 % of cadence)) [≤ 2 days] |
| APPROACHING | days_until ≤ max(3, round(cadence ÷ 3)) [≤ 7 days] |
| STABLE | otherwise |

### 6.6 Operational state rules

These describe coordination state only. The first matching rule wins:

1. **ACTIVE_COORDINATION**: an active request exists.
2. **ATTENTION**: the next requirement is APPROACHING, DUE or OVERDUE *and not covered*, or the network band is WEAK.
3. **WATCH**: any of the following: failed attempts in the last 30 days, a MODERATE network, ≥ 25 % of active network
   donors fatigued, unknown cadence, or an inactive patient record.
4. **HEALTHY**: none of the above.

Every state is returned with human-readable `operational_state_reasons`. A covered requirement is listed as
context and is never a reason for attention. With the default seed: 60 ACTIVE_COORDINATION, 13 WATCH, 3 ATTENTION,
4 HEALTHY.

### 6.7 API endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/patients/{patient_code}/digital-twin` | `DigitalTwinState` (404 if unknown) |
| GET | `/api/v1/requests/{request_code}/digital-twin-context` | `{ request: RequestCoordinationContext, digital_twin: DigitalTwinState }` (404 if unknown) |

The request context adds what the Adaptive Cascade will need: status, compatible donor groups, attempts and failures
so far, latest attempt outcome, latest recovery action and status, whether it is the patient's current request,
and the request's own timeline.

### 6.8 Frontend representation

Route `/patients/:patientCode/digital-twin` (lazy-loaded, as it carries Recharts). Entry points are the
**Digital Twin** nav item (PAT-0001), the overview's "Open Living Digital Twin" button, and the **Patients** list
(`/patients`). A patient selector in the header switches between all 80 patients.

| Card | Shows |
|---|---|
| Header | name, blood group, code, location, bridge group, operational state badge with meaning, clock |
| Requirement | days until expected requirement + recurrence badge, cadence, units, urgency, current request and its status |
| Donor network | strength score + band, meter, six donor counts, weighted score components |
| Coordination history | six metrics + **Attempts per request** stacked bar chart (failed vs successful, colour-blind-validated teal/amber, hidden data table for screen readers) |
| Recent activity | 30-day counts and a vertical timeline of the focus request (created → checks → contacted → no response → failure → recovery → accepted → secured) |
| Summary | deterministic summary, "why this state" reasons, and a note that this is operational coordination intelligence, not a medical assessment |

Every figure comes from the API; the UI hard-codes no metrics.

### 6.9 Future AI integration point

`DigitalTwinService` takes a `summarize: Callable[[DigitalTwinState], str]`, which is `deterministic_summary`
today. A future AI summarizer will pass the computed twin as structured context to the `AIProvider`
(`AITask.SUMMARIZE` / `COORDINATOR_ASSIST`), set `summary_source` accordingly, and fall back to the deterministic
text when AI is disabled or fails. The AI only *describes* the figures; every number and state stays rule-based.

## 7. Donor State Intelligence Engine ✅

> Every value is a **demo coordination metric** computed by deterministic rules from synthetic demonstration data.
> Nothing here is a medical eligibility, suitability or clinical recommendation, and no LLM computes any of it.
> Synthetic demonstration data — not for clinical use.

**Donor State vs Matching.** Donor State answers *"what is the current state of this donor, and how suitable are
they for this request, and why?"* for one donor (or a list someone provides). Matching, later, will answer *"which
donor should we choose for this request?"* by searching the whole pool. Donor State never searches or selects.

Code: `app/services/donor_state.py` (rules + `DonorStateEngine`), `app/repositories/donor_state_repository.py`
(queries), `app/schemas/donor_state.py` (`DonorStateAssessment` and related models).

### 7.1 Purpose

Replace "available / unavailable" with a structured, explainable state: availability, demo eligibility,
reliability, response behaviour, coordination fatigue, contact freshness, history and an operational priority,
each returned with its reasons.

### 7.2 Inputs and sources of truth

| Input | Source |
|---|---|
| Messaging behaviour | `donor_interactions` (status, type, timestamps), aggregated per donor in SQL |
| Coordination outcomes | `coordination_attempts` (success, failure by outcome), aggregated per donor in SQL |
| Registry inputs | the persisted `donor_states` row: declared availability, registry deferral flag, donation record |
| Request context | `blood_requests` + `app/core/blood.py` compatibility table (the single compatibility implementation) |
| Clock | `app/core/clock.py` (dataset reference time by default) |

**Persisted `DonorState` = seeded baseline snapshot. Donor State Engine = authoritative computed assessment.**
The engine reads only the registry-type fields that interactions cannot reveal: declared availability, the
deferral flag, and the donation count and last-donation date. It ignores the row's placeholder scores
(`reliability_score`, `response_rate`, `fatigue_score`, `current_priority_score`), which remain only as the
generator's seed output. The Digital Twin's network counts also come from this engine (section 6.4), so a donor's
state is identical everywhere in the app.

**Point in time.** Every rule is evaluated *as of* a moment, using only history before it. For a request:
`evaluate_at=auto` (default) assesses active requests **now** and resolved requests at the moment
**coordination began** (`requested_at`), so a finished request is judged on what was known when it started.
`now` and `request_start` force either view. For earlier moments, donations the dataset shows afterwards are
subtracted from the registry record.

### 7.3 Availability rules (first match wins)

| Status | Rule |
|---|---|
| INACTIVE | donor record inactive |
| TEMPORARILY_UNAVAILABLE | declared unavailable in the registry, or replied "unavailable" within the last 14 days |
| RECENTLY_CONTACTED | awaiting a reply, or contacted within the last 3 days (no repeat outreach) |
| AVAILABLE | otherwise (declared "limited" availability is noted and scores lower) |

### 7.4 Eligibility rules (demo coordination eligibility rules; every check is a gate)

1. **Blood-group compatibility** (request only): donor group in `COMPATIBLE_DONORS[request group]`.
2. **Active donor** record.
3. **No registry deferral flag** (synthetic).
4. **Donation interval**: no donation in the last 90 days (demo interval shared with the generator).

`eligible = all checks pass`. Each check is returned with a human-readable detail.

### 7.5 Reliability (coordination track record, 0–100)

```
positive = successful attempts + 0.2 × min(earlier registry donations, 10)
negative = 1.0 × no-response failures + 0.5 × declined/unavailable failures + 0.25 × other failures
reliability = round(100 × (positive + 1) ÷ (positive + negative + 2))      # Laplace smoothing: 50 with no evidence
bands: HIGH ≥ 70 · MEDIUM 45–69 · LOW < 45
```

Not answering is weighed more heavily than honestly declining. Smoothing keeps thin histories near 50 instead of
fabricating confidence, and `reliability_factors` lists the evidence used.

### 7.6 Response behaviour

Counts settled interactions (a message unanswered at the evaluation time counts as pending, not as no-response):
responses = responded + accepted + declined + unavailable.

- `response_rate`, `acceptance_rate` (accepted ÷ donation requests) and `no_response_rate` are reported only with
  **≥ 3 interactions**; otherwise they are `null` and `data_sufficiency = INSUFFICIENT_DATA`. Of the 6,946 donors,
  5,887 have insufficient data, which is honest for a dataset where most donors are rarely contacted.
- `response_score = round(100 × (responses + 1) ÷ (interactions + 2))` is always defined and feeds priority.

### 7.7 Coordination fatigue (outreach load, 0–100; not medical fatigue)

```
fatigue = min(10 × contacts in last 30 days, 50)
        + min(15 × (distinct requests contacted for in 30 days − 1), 30)
        + 20 if the donor donated within the last 120 days
bands: LOW < 30 · MODERATE 30–59 · HIGH ≥ 60
```

Across all donors: 6,046 LOW, 654 MODERATE, 246 HIGH. Rare-group donors concentrate the high values because every
rare-group request contacts the same small pool (PAT-0001's B− network: 48 % highly fatigued).

### 7.8 Contact freshness (0–100)

`freshness = min(100, round(100 × days since last contact ÷ 30))`, or 100 when there is no contact on record.
A donor contacted today scores 0, so a recently contacted donor is not automatically re-prioritised.

### 7.9 Priority (operational ranking score, 0–100)

Eligibility, including compatibility, is a **gate**: if any check fails, `priority_score = 0` and the band is
`NOT_ELIGIBLE`, so an incompatible donor can never rank above a compatible one. Otherwise:

```
priority = Σ weight × factor score ÷ 100
  availability  AVAILABLE 100 (declared limited 60) · RECENTLY_CONTACTED 40 · otherwise 0
  reliability   reliability score (7.5)
  response      response_score (7.6)
  fatigue       100 − coordination fatigue
  freshness     contact freshness (7.8)
  request fit   (blood group: exact 100 / compatible substitute 70 + location: same city 100 / district 75 / else 40) ÷ 2
bands: HIGH ≥ 70 · MEDIUM 45–69 · LOW < 45 · NOT_ELIGIBLE (gated)
```

| Weight profile | availability | reliability | response | fatigue | freshness | request fit |
|---|---|---|---|---|---|---|
| GENERAL (no request) | 30 | 25 | 20 | 15 | 10 | — |
| STANDARD (LOW / MODERATE urgency) | 25 | 25 | 20 | 10 | 10 | 10 |
| URGENT (HIGH / CRITICAL urgency) | 25 | 20 | 30 | 8 | 7 | 10 |

Urgent requests favour donors who answer quickly. Weights are returned by the API with every assessment.
A donor with no history lands near the middle on reliability and response, so proven donors rank slightly above
unknown ones. Balancing the two belongs to the Matching Engine.

### 7.10 Explainability

Every assessment returns:
- `priority.priority_factors`: per factor, its score, weight and contributed points (they add up to the score);
- `priority.priority_reasons`: ordered sentences tagged POSITIVE / NEUTRAL / NEGATIVE, failed eligibility checks
  first (e.g. "Exact blood group match (B−)", "Currently available", "Limited messaging history: 0 of 2 messages
  answered", "Recently contacted (today)");
- per-section reasons: `availability_reason`, eligibility `checks`, `reliability_factors`, `fatigue_reasons`.

A future AI layer may turn this structure into prose; it would never change the values.

### 7.11 API endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/donors/{donor_code}/state` | `DonorStateAssessment` now (GENERAL weights) |
| GET | `/api/v1/donors/{donor_code}/state-for-request/{request_code}?evaluate_at=auto\|now\|request_start` | `{ request, compatibility, evaluation_note, state }` |
| GET | `/api/v1/requests/{request_code}/donor-comparison?donor_codes=A,B&evaluate_at=…` | candidates ranked by priority, recommended donor and reason |

Unknown donors and requests return 404 with a specific message. A separate `explain-priority` endpoint was not
added, since the state-for-request response already carries the full explanation. The comparison defaults to the
donors the request's cascade contacted; it ranks only the listed donors (1–10) and is not the Matching Engine.

Performance: a constant number of queries for any batch of donors (per-donor GROUP BY aggregation; no donor
outside the batch is loaded). A single assessment takes about 4–6 ms in-process (target: under 100 ms).

### 7.12 Frontend representation

- `/donors`: paginated donor list with demo shortcuts (DON-00001 / DON-00002 for DEMO-REQUEST-001) and open-by-code.
- `/donors/:donorCode`: the donor state page (lazy-loaded). Its two modes are *General state* and *For a request*
  (`?request=…&at=auto|now|request_start`):
  - header with operational priority score and band;
  - compatibility banner and evaluation note (request mode);
  - **Current state** tiles: availability, eligibility, reliability, response rate, coordination fatigue and
    contact freshness, plus the eligibility checklist;
  - **Why this donor?**: tagged reasons and the factor table (score, weight, points);
  - **Historical behaviour**: message and coordination counts, reliability evidence and fatigue reasons
    (counts only; with 0–16 interactions per donor a chart would add nothing);
  - **Donor comparison** (request mode): reusable `DonorComparisonTable` with the cascade's donors plus this donor,
    an "add donor" control, the recommended donor and the reason.
- The Digital Twin timeline links donor codes to their state for that request.

No score is hard-coded in the UI; every value comes from the API.

### 7.13 Relationship to the Matching Engine

Implemented in section 8. Matching (1) selects candidate donors in SQL (compatibility, location, active), (2) calls
`DonorStateEngine.assess_donors(donors, as_of, request)` once per request, (3) ranks and diversifies the
results (for example, balancing proven donors against untested ones, or sparing fatigued rare-group donors), and
(4) will hand the ranked list to the Adaptive Cascade. The Donor State Engine's gate guarantees Matching can never
promote an ineligible or incompatible donor.

## 8. Matching Engine ✅

> Deterministic **coordination recommendations** from synthetic demonstration data: candidates ranked by operational
> priority under demo coordination eligibility rules. Not a medical recommendation, clinical suitability assessment
> or guarantee of any donor. No LLM is used. Synthetic demonstration data — not for clinical use.

| Engine | Question it answers |
|---|---|
| **Donor State Engine** | "What is this donor's current state?" |
| **Matching Engine** | "Which eligible donors are best for this request?" |
| **Adaptive Cascade** (future) | "What should we do next when coordination succeeds or fails?" |

Code: `app/services/matching.py` (`MatchingEngine` + pure scoring rules), `app/repositories/matching_repository.py`
(SQL discovery and request history), `app/schemas/matching.py`, `app/core/geo.py` (Haversine, bounding box).

### 8.1 Purpose

Turn a blood request into a ranked, explained list of candidate donors, with every unsuitable donor accounted
for. The list is the input the Adaptive Cascade will work through.

```
BLOOD REQUEST → candidate discovery (SQL) → compatibility gate (SQL) → eligibility gate (Donor State Engine)
  → candidate state assessment (one Donor State batch) → contextual ranking → ranked list + explanation
```

### 8.2 Candidate discovery

All filtering happens in SQL; the 6,946 donors are never loaded into Python.

1. **Request location**: requests store no coordinates, so the request is placed at the centroid of the synthetic
   donor coordinates in the request's city (`AVG(latitude), AVG(longitude)`), which is deterministic and
   data-derived. If the city has no donors, the location is unknown: there is no radius, and `distance_km = null`
   ("Location unavailable").
2. **Radius steps**: 30 km → 80 km → whole region. The smallest step that yields at least 40 active compatible
   donors is used, so a rare blood group in a small city widens automatically (`radius_expanded`). A bounding box
   (`latitude/longitude BETWEEN …`) does the SQL filtering; exact distance is computed later with Haversine.
3. **Pool cap**: at most the 400 nearest donors (SQL `ORDER BY` planar distance, then `donor_code`) are assessed.
   Only common groups in the metro area hit the cap (`pool_capped`).
4. **Discovery counts** (one aggregate query) report what was filtered: inactive donors, incompatible donors and
   compatible donors outside the radius.

### 8.3 Compatibility filtering

Compatibility uses the single table in `app/core/blood.py` (simplified red-cell ABO/Rh demo table, not clinical
guidance), applied in the discovery `WHERE` clause:

| Request | Compatible donor groups |
|---|---|
| O− | O− |
| O+ | O+, O− |
| A− | A−, O− |
| A+ | A+, A−, O+, O− |
| B− | B−, O− |
| B+ | B+, B−, O+, O− |
| AB− | AB−, A−, B−, O− |
| AB+ | all groups |

The Donor State Engine re-checks compatibility as a gate, so an incompatible donor can never be ranked.

### 8.4 Eligibility filtering

Every pooled donor is assessed by the Donor State Engine for the request. A donor is **excluded** (kept in the
response, never ranked) when:
- a Donor State eligibility gate fails: recent donation (90-day demo interval), registry deferral flag, inactive
  record or incompatible blood group; or
- the request's own history makes another contact pointless: the donor *declined or replied unavailable* to this
  request's availability check, *already failed* an attempt for this request, or is *already engaged* in this
  request's cascade.

Excluded donors keep their `exclusion_reason`; `include_excluded=true` lists them (nearest first), and
`top_exclusion_reasons` counts both gate exclusions and discovery filters.

### 8.5 Donor State integration

Matching calls `DonorStateEngine.assess_donors(donors, as_of, request)` **once** for the whole pool. That batch
costs a constant number of grouped queries, regardless of pool size. Availability, eligibility, reliability, response,
fatigue, freshness and the donor priority score all come from that single source of truth; Matching duplicates no
donor formula. The patient's current Digital Twin is consumed (not recomputed) for context: operational state,
active request, whether the requirement is covered, and network strength.

### 8.6 Request-fit scoring

```
request_fit = 0.6 × blood fit + 0.4 × patient link
  blood fit    exact group 100 · compatible substitute 60 (scarcer groups such as O− are conserved)
  patient link donated for this patient before 100 · member of the patient's bridge group 80 · none 50
```

The donor priority score already contains a coarse request fit (blood match + same city, 10 %). Request fit adds
the patient relationship and a stronger preference for exact matches.

### 8.7 Geographic scoring

`distance_km` is the Haversine distance from the request location to the donor's **synthetic** coordinates (they
represent no real person). `geographic_fit = round(100 × max(0, 1 − distance ÷ 50 km))`: 100 at the request, 50 at
25 km, 0 at 50 km or more, and 50 (neutral) when the location is unknown.

### 8.8 Urgency handling and coordination context

```
match_score = clamp(0, 100, round(Σ weight × component ÷ 100) + strategy adjustment)
```

| Profile | Donor state priority | Request fit | Geographic fit | Coordination context | Exploration bonus | Unproven discount |
|---|---|---|---|---|---|---|
| URGENT (HIGH / CRITICAL) | 50 | 15 | 20 | 15 | 0 | −5 |
| STANDARD (LOW / MODERATE) | 45 | 20 | 15 | 20 | +5 | 0 |

Urgency changes weights and the strategy adjustment, never eligibility. Urgent requests lean on donor state (whose
own URGENT profile already favours response behaviour) and proximity, and discount donors whose readiness is
unproven.

**Coordination context** (starts at 100, request-specific): replied *available* to this request's check (no
penalty, positive reason); no reply to the check −30; check awaiting reply −15; failed attempts elsewhere in the
last 30 days −25 each (max −50); ≥ 3 contacts in 30 days −20; contacted within the last few days −20. Known dead
ends exclude the donor instead (8.4).

### 8.9 Exploration vs exploitation

The ranking must not always favour the same proven donors. Each eligible candidate gets a deterministic
`candidate_strategy`:

| Strategy | Rule |
|---|---|
| RELIABLE | proven (≥ 1 successful attempt, ≥ 3 interactions, or reliability evidence ≥ 2, e.g. 10 earlier donations), reliability ≥ 70 and, when measurable, response rate ≥ 60 % |
| EXPLORATION | not proven, yet available, low coordination fatigue, contact freshness ≥ 70 and request fit ≥ 60 |
| BALANCED | everything else |

For LOW / MODERATE urgency, EXPLORATION candidates get **+5** ("Selected for controlled exploration (+5)"), so
promising under-tested donors surface. For HIGH / CRITICAL urgency there is no bonus and every unproven donor gets
**−5** ("uncertainty discount"), so proven readiness wins when time matters. Nothing is random: the same request,
dataset and evaluation time always produce the same ranking.

Examples from the default seed: a HIGH-urgency AB+ request in Hyderabad is led by RELIABLE donors, while a
LOW-urgency AB− request in Siddipet is led by EXPLORATION donors.

### 8.10 Ranking

Eligible candidates are sorted by **match score ↓, donor priority ↓, distance ↑, donor_code ↑**. Donor code is the
final tie-breaker, so identical scores always produce the same order (DEMO-REQUEST-001 has a three-way tie at 86).
`limit` (default 10, 1–50) controls how many ranked candidates are returned; counts and averages always cover all
eligible candidates.

### 8.11 Explainability

Each candidate returns its rank, donor identity, `distance_km`, availability, reliability, response rate (or
insufficient data), fatigue, freshness, donor priority, request fit, geographic fit, context, strategy adjustment,
match score, strategy and `strategy_reason`, plus:
- `score_breakdown`: each component's score, weight and points (they add up, with the adjustment, to the match score);
- `reasons`: ordered sentences tagged POSITIVE / NEUTRAL / NEGATIVE, for example "Eligible under demo coordination
  rules", "Exact blood group match (B−)", "Currently available", "High historical reliability (75/100)",
  "7.1 km from the request location (synthetic coordinates)", "Low coordination fatigue", "Not recently contacted",
  "Selected for controlled exploration (+5)".

`matching_summary` gives the top candidate, the average match score, candidates by strategy and the top exclusion
reasons (each tagged `gate` or `discovery`). A future AI layer may narrate this structure; the deterministic ranking
remains the source of truth.

### 8.12 Evaluation time

Matching follows the Donor State Engine's semantics via the shared `DonorStateEngine.evaluation()` rule:
- `auto` (default): active requests are evaluated **now** (dataset clock); resolved requests at **request start**
  (`requested_at`), using only history known before coordination began;
- `now` / `request_start` force either view.

Request history (check replies, attempts, recent failures, earlier donations for the patient) is filtered to the same
moment. For DEMO-REQUEST-001, `request_start` shows the candidates as they stood before the cascade ran; `now` shows
them after it (DON-00001 excluded for its failed attempt, DON-00002 for its fresh donation, three donors who
declined this request's check excluded).

### 8.13 API

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/requests/{request_code}/matching?limit=10&include_excluded=false&evaluate_at=auto` | `MatchingResult`: request, evaluation, Digital Twin context, discovery, pool / eligible / excluded counts, weights, ranking, excluded, matching summary |

Read-only; `limit` outside 1–50 or an unknown `evaluate_at` returns 422; an unknown request returns 404.

### 8.14 Performance considerations

Per request: a few SQL queries for discovery (counts and the capped pool), one Donor State batch (constant query
count), four grouped request-history queries and one Digital Twin build. No per-donor queries.
Measured in-process: **~60 ms** for DEMO-REQUEST-001 (156 donors assessed), ~130–150 ms for a capped 400-donor AB+
pool (target: under 500 ms). No new indexes or caches were needed.

### 8.15 Relationship with the Adaptive Cascade

Implemented as a simulation in section 9. The cascade consumes `ranking` as its candidate list and re-matches
before each wave with its contacted donors excluded (`exclude_donor_codes`) and any widened radius
(`radius_step`). A persisted cascade will additionally: it decides contact order (waves), channels and response
windows, records attempts, and on failure calls Failure Autopsy and Self-Healing, then re-runs Matching with
`evaluate_at=now`. The exclusions in 8.4 already stop a re-run from recommending a donor who has declined or failed
for the request. Matching never contacts anyone and never decides what happens after an outcome.

### 8.16 Frontend representation

Route `/requests/:requestCode/matching` (lazy-loaded); reached from the **Matching** nav item (DEMO-REQUEST-001),
the Digital Twin requirement card ("Candidate matching") and the donor state page in request mode.

| Section | Shows |
|---|---|
| Header | request code, patient (link to twin), blood group, urgency, status, location, Digital Twin state and network strength, evaluation selector (auto / now / at request start) with its note |
| Candidate overview | evaluated / eligible / excluded counts, average match, candidates by strategy, radius and weights |
| Ranked candidates | rank badge, donor, match score bar, distance, reliability, response rate (or "Insufficient"), fatigue, strategy; 10 / 25 / 50 rows; select a row to explain it |
| Why #k? | match score, tagged reasons, strategy explanation, score breakdown (score × weight = points, adjustment, total), link to the donor's full state for the request |
| Excluded candidates | collapsible: gate exclusions with counts, discovery filters with counts, nearest excluded donors with their reasons |

All values come from the API; nothing is hard-coded.

## 9. Adaptive Cascade Engine (simulation) ✅

> A **deterministic, in-memory simulation**. Nothing is persisted, nobody is contacted, and every donor response is
> simulated from synthetic demonstration data. Synthetic demonstration data — not for clinical use.

| Engine | Question it answers |
|---|---|
| Donor State | "What is this donor's current state?" |
| Matching | "Which eligible donors are best for this request?" |
| **Adaptive Cascade** | "Who do we contact first, and what do we do next when outreach succeeds or fails?" |

Code: `app/services/cascade.py` (`AdaptiveCascadeEngine` + pure rules), `app/schemas/cascade.py`.

### 9.1 Loop

```
Matching ranking → Wave 1 (top N donors contacted in parallel) → simulated responses
  → secured? ── yes → FULFILLED → learning preview
        └─ no → wave autopsy → self-healing decision → re-matching (contacted donors excluded, decision applied)
               → Wave 2 → … → FULFILLED, or ESCALATED (coordinator review / blood-bank referral)
```

Scope (agreed): the cascade itself. Failure Autopsy (section 10) and Self-Healing (section 11) now plug in behind the
original response structures; only the learning preview is still a preliminary rule set.

### 9.2 Wave policy (by request urgency)

| Urgency | Wave size | Response window |
|---|---|---|
| LOW | 2 | 360 min |
| MODERATE | 2 | 240 min |
| HIGH | 3 | 120 min |
| CRITICAL | 4 | 60 min |

`wave_size` can be overridden (1–6), and `max_waves` defaults to 5 (1–8). Outreach starts 15 minutes after the
evaluation time, with sends spaced 2 minutes apart. A wave closes when the requirement is secured, when every contacted
donor has replied, or when its window ends; the next wave starts 10 minutes later. The initial channel is simulated
SMS for donors with a known response rate of at least 70 %; everyone else gets a simulated call (HIGH/CRITICAL) or
SMS (otherwise).

### 9.3 Re-matching

Before every wave after the first, the cascade calls the **Matching Engine** again with
`exclude_donor_codes = donors already contacted` (excluded with reason "Contacted earlier in this cascade") and the
healing decision's `radius_step`. Matching therefore stays the single source of the ranking, and the Donor State
Engine stays the single source of donor state. Because the simulation writes nothing, re-matching sees the same data
minus the contacted donors, plus the decision's changes.

### 9.4 Simulated responses (deterministic)

```
reply chance  = clamp(5–95 %, response_score ÷ 100 × channel factor × stress)   call 1.15 · SMS 1.0 · app 0.9
accept chance = clamp(5–95 %, reliability ÷ 100 × availability factor × (1 − fatigue ÷ 200))
                availability factor: available 1.0 · recently contacted 0.6 · temporarily unavailable 0.15
```

Each draw is `SHA-256(seed | request | donor | purpose)` mapped to [0, 1), so there is no `random()` and no clock:
the same request, data, evaluation time and seed always produce the same story. A replying donor who does not accept
is split evenly between *declined* and *unavailable*. Reply times fall between 10 % and 90 % of the window.
Acceptances secure units in the order they arrive; later acceptors are kept on standby.

**Calibration**: with no stress, a top candidate succeeds about half the time per contact, matching the synthetic
history (about 52 % of recorded coordination attempts succeed). Three parallel contacts therefore usually secure a
unit in wave 1. To explore adaptation honestly rather than distort the calibration, two what-if controls exist:
- `seed`: a different deterministic scenario;
- `response_stress`: `none` (×1.0), `moderate` (×0.75) or `severe` (×0.5) applied to every reply chance.

### 9.5 Preliminary autopsy and self-healing rules

> **Superseded.** The self-healing rules below were the Phase 6 placeholder. The cascade now delegates the
> decision to the Self-Healing Engine ([section 11](#11-self-healing-engine-)); `choose_healing` survives only
> as a compatibility adapter. The wave autopsy counts remain.

The wave autopsy counts accepted / declined / unavailable / no-response contacts and names the dominant failure cause
(ties favour *no response*). The self-healing decision follows these rules, first match wins:

1. last allowed wave → **escalate** (`BLOOD_BANK_REFERRAL` if CRITICAL, otherwise `HUMAN_COORDINATOR_REVIEW`);
2. no candidates left → `EXPANDED_SEARCH` (next radius step), or escalate at the widest radius;
3. third failed wave or later → `EXPANDED_SEARCH` while a wider radius exists;
4. second failed wave or later, with bridge-group donors remaining and not yet used → `BRIDGE_GROUP_ESCALATION`
   (members are moved to the front of the ranking, keeping their relative order);
5. no response dominated → `ALTERNATIVE_DONOR`: simulated calls for all later waves, one more donor per wave (max 6);
6. otherwise → `NEXT_DONOR`.

Across 30 seeds per stress level, all of these paths occur, including escalation.

### 9.6 Learning preview

These signals are not persisted; they use the same magnitudes as the synthetic `learning_events`. Each contact
records SUCCESSFUL_MATCH +0.8 (secured), +0.4 (standby), NO_RESPONSE −0.35, DONOR_DECLINED −0.2 or
FAILED_MATCH −0.1 (unavailable). Each applied recovery records RECOVERY_SUCCESS +0.6 if the next wave secured a unit,
otherwise RECOVERY_FAILURE −0.3. The Learning Engine will persist and apply these.

### 9.7 DEMO-REQUEST-001

Evaluated as of request start (B−, HIGH urgency: waves of 3, 120-minute window):
- **default seed**: wave 1 contacts the top three matched donors by simulated call; one accepts, so the
  requirement is secured in one wave (3 contacts).
- **seed 25**: all three wave-1 donors miss the window → autopsy: dominant cause *no response* → self-healing:
  `ALTERNATIVE_DONOR` (calls, wave of 4) → re-matching drops the contacted donors (122 → 119 eligible) → wave 2:
  **DON-00002** replies first and secures the unit, and three later acceptors stand by. This is the closed loop
  from the product diagram.
- **seed 27, severe stress**: four waves: initial → alternative donor → bridge-group escalation → expanded search
  → secured.

The response also lists the request's **recorded** attempts (DON-00001 failed, DON-00002 succeeded) so the simulation
can be compared with what happened in the dataset.

### 9.8 API

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/requests/{request_code}/cascade?evaluate_at=auto&max_waves=5&wave_size=&seed=20261008&response_stress=none` | `CascadeResult`: parameters, outcome (FULFILLED / ESCALATED), units, waves (contacts, autopsy, healing), escalation, learning preview, recorded attempts |

Read-only (GET), with no side effects. Invalid parameters return 422 and an unknown request returns 404. A
default run takes about 70 ms in-process and about 150 ms over HTTP; each extra wave re-runs Matching (about 60 ms).

### 9.9 Frontend representation

Route `/requests/:requestCode/cascade` (lazy-loaded); reached from the **Cascade** nav item (DEMO-REQUEST-001) and
from the Matching page ("Simulate adaptive cascade"). It shows:
- header: request, patient, the wave policy and the link back to the candidate ranking;
- controls: scenario seed (with "Next scenario"), response stress test, max waves and evaluation point, all
  stored in the URL so a scenario can be shared;
- outcome banner: secured in N waves / escalated, contacts, simulated time, deadline, secured donor;
- wave cards: rank, donor, channel, reply and accept chances, simulated response, detail; between waves, the
  **wave autopsy** and **self-healing** decision (or escalation);
- learning preview and "What actually happened" (the recorded attempts).

## 10. Failure Autopsy Engine ✅

> **Failure Autopsy is a deterministic operational analysis layer. It does not diagnose medical causes
> and does not make medical decisions.** Synthetic demonstration data — not for clinical use.

| Engine | Question it answers |
|---|---|
| Donor State | "What is this donor's current state?" |
| Matching | "Which eligible donors are best for this request?" |
| Adaptive Cascade | "Who do we contact first, and what do we do next when outreach succeeds or fails?" |
| **Failure Autopsy** | "Why did this fail, and what pattern does the evidence suggest?" |
| Self-Healing (hook) | "What should the system actually change?" — decides, using the autopsy's recommendation as one input; never bound by it |
| Learning (preview) | "What should be remembered for future coordination?" |

**Autopsy recommends. Self-Healing decides. Learning remembers.** The three are never merged: Failure
Autopsy returns a `recommended_action` in its own vocabulary (`RecoveryRecommendation`) and never writes to,
or chooses, the cascade's actual next wave; the Self-Healing Engine (section 11) makes that decision, using the
autopsy's pattern as one input alongside wave number, remaining candidates, urgency and the safety limits.

Code: `app/services/failure_autopsy.py` (pure rules + `FailureAutopsyEngine`), `app/repositories/failure_autopsy_repository.py`
(RECORDED-path queries), `app/schemas/failure_autopsy.py`.

### 10.1 Purpose

Turn one or more failed coordination attempts into a structured, evidence-based explanation: what failed,
who/what failed, why, whether the cause looks donor-specific, channel-specific, timing-related or
network/context-related, whether it is an isolated failure or part of a pattern, and what recovery might be
worth considering — never performing it.

### 10.2 Failure taxonomy

Reuses the existing `FailureCategory` enum (`app/models/enums.py`), extended with four values the autopsy
needed and the original dataset generator did not: `RECENT_DONATION`, `DEFERRAL`, `ALREADY_CONTACTED`,
`CASCADE_EXHAUSTED`. No parallel taxonomy was created.

| Category | Meaning |
|---|---|
| `NO_RESPONSE` | No reply before the response window closed |
| `DECLINED` | Donor explicitly declined |
| `UNAVAILABLE` | Donor replied unavailable |
| `CONTACT_FAILURE` | Outreach could not be delivered |
| `FATIGUE` | Donor paused due to coordination fatigue (historical dataset only) |
| `RECENT_DONATION` | Excluded by the 90-day demo donation-interval rule |
| `DEFERRAL` | Excluded by the registry deferral flag |
| `ALREADY_CONTACTED` | Already engaged for this request (declined, failed, or contacted in this cascade) |
| `CASCADE_EXHAUSTED` | The pool for this request is exhausted |
| `OTHER` | Anything else |

Severity reuses `FailureSeverity` (`LOW · MEDIUM · HIGH · CRITICAL`) — `MEDIUM` is this codebase's existing
name for what the brief calls "MODERATE". Severity for a CRITICAL-urgency request is bumped up one level
(never past `CRITICAL`): every hour without a confirmed donor matters more when the need is critical.

### 10.3 Individual failure analysis

`analyze_individual(observation, …)` answers all of: what failed (`failure_type`), who (`affected_donor`),
why (`summary` + `evidence`), and four yes/no interpretive flags — `donor_specific`, `channel_specific`,
`timing_related`, `network_related` — set from whether the failure belongs to a detected batch pattern.

```
severity    CASCADE_EXHAUSTED → CRITICAL · part of a pattern → HIGH · isolated DECLINED → LOW · otherwise MEDIUM
confidence  fixed per failure type: explicit replies (DECLINED/UNAVAILABLE 0.90–0.95) are more certain than
            an absence of information (NO_RESPONSE 0.90); CONTACT_FAILURE/OTHER are least certain (0.40–0.60)
```

Evidence is never invented: it is built only from the failure's own recorded or simulated fields — the
channel that was actually used, the outcome that was actually recorded, and (for RECORDED failures) the
dataset's own `failure_reason` text.

### 10.4 Pattern detection

`detect_patterns(observations, context)` finds every pattern the batch's evidence supports (not just the
first), most specific/certain first; it never forces one when the evidence doesn't support it, and returns
`[]` immediately for zero observations (so a placeholder "nothing computed" context is never misread as a
pattern — see 10.14).

| Pattern | Trigger | Recommends |
|---|---|---|
| `CANDIDATE_POOL_EXHAUSTION` | nothing eligible remains in radius, and nothing further out either | `HUMAN_COORDINATOR` |
| `CHANNEL_RESPONSE_FAILURE` | ≥ 2 `NO_RESPONSE`, all via the same channel | `SWITCH_CHANNEL` |
| `BRIDGE_GROUP_FAILURE` | ≥ 2 bridge-group-member failures, over half the batch | `TRY_BRIDGE_GROUP` |
| `LOCAL_POOL_FAILURE` | ≤ 2 candidates left in radius, but the wider region has more | `EXPAND_SEARCH_RADIUS` |
| `RECENT_DONATION_POOL` | over half the batch are `RECENT_DONATION`/`DEFERRAL` gate exclusions | `RE_RUN_MATCHING` |
| `RESPONSE_WINDOW_FAILURE` | ≥ 2 `NO_RESPONSE`, across more than one channel | `INCREASE_WAVE_SIZE` |
| `INDIVIDUAL_DONOR_FAILURE` | exactly one failure (marker, not a genuine pattern) | matches that failure's own recommendation |
| `UNKNOWN_PATTERN` | ≥ 2 failures, causes mixed, no rule matches (marker) | `TRY_ALTERNATIVE_DONOR` |

`dominant_pattern` always carries a `pattern_type` whenever at least one failure was analysed — the last two
rows are markers filled in when no genuine multi-failure pattern was found, so the API and UI never have to
handle a bare `null` pattern type. `pattern_detected` is `true` only for a genuine pattern (the first six rows).

### 10.5 Root cause vs symptom

Language is deliberately hedged to the evidence available: `"Pattern indicates…"`, `"Evidence suggests…"`.
A channel is only named as the cause (`"…a simulated call response failure…"`) when every `NO_RESPONSE` in
the batch really did share that one channel; when they don't, the engine falls back to the weaker,
more honest `RESPONSE_WINDOW_FAILURE` ("the window itself — not one channel — looks like the likely
operational cause") rather than naming a channel the data doesn't implicate.

### 10.6 Evidence chain

Every `EvidenceItem` has a `type` (`ATTEMPT · INTERACTION · OUTCOME · PATTERN · CONTEXT`), a `description`
built from real data, and a `reference` (a `failure_code`/`attempt_code` for RECORDED evidence, a `donor_code`
for SIMULATED) when one exists. Pattern-level evidence cites the real supporting count and, for
context-based patterns, the real remaining/outside-radius counts already computed by Matching.

### 10.7 Rule confidence

`rule_confidence` (0–1) is a fixed, documented, deterministic score — **never** a machine-learning
confidence. Individual-failure confidence is a per-category constant (10.3). Pattern confidence starts
from a per-pattern base (0.60–0.95, context-counted patterns like `CANDIDATE_POOL_EXHAUSTION` and
`RECENT_DONATION_POOL` rank highest since they are directly counted, not inferred) and rises by 0.03 per
corroborating failure beyond the minimum, capped at +0.15 and an overall ceiling of 0.97 — a rule never
claims near-certainty.

### 10.8 Recovery recommendations

`RecoveryRecommendation` is the shared recovery vocabulary (distinct from the persisted `RecoveryActionType`): `TRY_ALTERNATIVE_DONOR · SWITCH_CHANNEL · INCREASE_WAVE_SIZE · TRY_BRIDGE_GROUP ·
EXPAND_SEARCH_RADIUS · RE_RUN_MATCHING · HUMAN_COORDINATOR · BLOOD_BANK_ESCALATION`. Since Phase 8 the Self-Healing Engine decides with the same names (plus `NO_CHANGE`), so the
vocabulary is shared rather than duplicated; the separation is of responsibility, not of names. Keeping the roles apart
is what makes "autopsy recommends, self-healing decides" structural rather than just a UI label — the two
engines cannot accidentally share one value that means "autopsy executed this."

### 10.9 Recorded vs simulated

| | RECORDED | SIMULATED |
|---|---|---|
| Source | `Failure` rows already in the synthetic dataset | one Adaptive Cascade wave's failed contacts, in memory |
| Meaning | "what actually happened" | "what the simulation produced" |
| Reached via | `GET /failures/autopsy`, `GET /failures/{code}/autopsy` | embedded in `GET /cascade`'s `waves[].failure_autopsy` |
| `source` field | `RECORDED` | `SIMULATED` |

The two are never mixed into one `RequestAutopsy`; the frontend's "what actually happened" vs "simulated
cascade" split (section 9) stays intact, and the recorded path is additionally surfaced, with its own
`RequestAutopsy`, inside the cascade page's "What actually happened" card.

### 10.10 Cascade integration

After every failed wave, `AdaptiveCascadeEngine` builds `FailureObservation`s from that wave's non-accepted
contacts and a `PatternContext` entirely from values Matching already computed for the wave (no extra
queries), then calls `FailureAutopsyEngine.analyze_simulated(...)`. This sits **alongside**, not instead of,
the plain `wave_autopsy()` response counts from section 9. The Self-Healing Engine (section 11) then decides
the next wave's shape from the autopsy:

```
Wave N → failed contacts → Failure Autopsy (recommends) ─┐
                         → Self-Healing.plan() (decides) → apply → re-match ── Wave N+1
```

`CascadeWave.failure_autopsy: RequestAutopsy | None` is an additive field; `autopsy`/`healing` are untouched,
so every Phase 6 interface and test kept working unmodified.

### 10.11 API

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/requests/{request_code}/failures/autopsy?evaluate_at=` | `RequestAutopsy` for every RECORDED Failure on the request |
| GET | `/api/v1/requests/{request_code}/failures/{failure_code}/autopsy` | `IndividualFailureAutopsy` for one RECORDED failure |

Both read-only; both 404 on an unknown request or failure code. The simulated path has no endpoint of its
own — it is embedded in `GET /requests/{request_code}/cascade`'s wave data (section 9).

### 10.12 Frontend

`FailureAutopsyPanel` renders one `RequestAutopsy`: failure count, source badge (RECORDED/SIMULATED),
dominant pattern with severity and confidence, interpretation, evidence, recommended action, and a
collapsible list of individual failures each with its own evidence and flags. It is used in two places on
the existing `/requests/:requestCode/cascade` page (no new page was added):

- between waves, via `HealingConnector`, showing the SIMULATED autopsy for that wave, immediately followed
  by a visually distinct Self-Healing decision panel ("What should change?", section 11.10) — so Autopsy never
  reads as if it performs the recovery itself;
- inside "What actually happened", showing the RECORDED autopsy for the request's real dataset history,
  fetched separately via the standalone endpoint.

### 10.13 Performance

A constant number of queries regardless of failure count: one or two for the recorded path (the failures
themselves, plus the Matching Engine's own queries for candidate-pool context), zero extra for the simulated
path (built entirely from data the cascade already has). Measured live: the request-level RECORDED endpoint
takes 60–80 ms; the embedded SIMULATED analysis adds negligible time to a cascade run (well under the 200 ms
target).

### 10.14 Limitations

- Demo-calibrated thresholds (minimum pattern size, local-pool threshold, confidence constants) are tuned
  against this synthetic dataset's scale, not derived from a larger statistical study.
- Pattern detection works on one batch at a time (one wave, or one request's full recorded history) — it
  does not yet look for patterns across multiple requests or over the donor network as a whole.
- A zero-observation batch always returns no pattern by construction (10.4); this was caught by a dedicated
  regression test after an earlier version briefly allowed a placeholder "no context computed" value to be
  misread as `CANDIDATE_POOL_EXHAUSTION`.
- No AI/LLM is used anywhere in this engine; a future AI layer may narrate `RequestAutopsy` in prose, but the
  deterministic rules above remain the only source of the classification, pattern, severity, confidence and
  recommendation.

## 11. Self-Healing Engine ✅

> **Self-Healing is a deterministic coordination-recovery layer.** It changes how outreach is organised
> or hands the request to people. It never diagnoses, never decides treatment, never overrides clinical
> decisions and never claims a donor will be available. Synthetic demonstration data — not for clinical use.

| Engine | Question it answers |
|---|---|
| Adaptive Cascade | "Who was contacted and what happened?" |
| Failure Autopsy | **"What happened?"** |
| **Self-Healing** | **"What should change?"** |
| Learning (preview) | **"What should be remembered?"** |

Code: `app/services/self_healing.py` (policy, plan, apply), `app/services/self_healing_report.py` (API report),
`app/schemas/self_healing.py`. The cascade contains **no recovery policy**: after a failed wave it calls
`SelfHealingEngine.plan(request_code, cascade_state, autopsy)`, applies the returned plan with
`SelfHealingEngine.apply(plan, settings)` and re-runs Matching.

### 11.1 Architecture

```
Wave fails → Failure Autopsy (what happened?) → Self-Healing.plan (what should change?)
          → RecoveryPlan → apply safe changes → re-run Matching (contacted donors excluded) → next wave
```

The engine is pure: no I/O, no clock, no randomness, no LLM. It reads a `CascadeState` (urgency, wave number,
wave size, channel, radius, donors contacted, eligible/fatigued/bridge candidates remaining, recovery attempts,
channel switches, failure totals) and the autopsy's dominant pattern, severity and confidence. It does not
analyse failures itself and does not rank donors; those stay in Failure Autopsy and Matching.

### 11.2 Recovery taxonomy

One shared vocabulary, `RecoveryRecommendation` (no duplicate enum): the autopsy recommends one of these, the
engine decides with the same names, plus `NO_CHANGE`.

| Action | Meaning |
|---|---|
| `NO_CHANGE` | Nothing is outstanding |
| `RE_RUN_MATCHING` | Recalculate the ranking without donors already contacted |
| `SWITCH_CHANNEL` | Next wave moves to a simulated call (and widens by one donor) |
| `INCREASE_WAVE_SIZE` | Contact one more donor per wave (up to the limit); calls are pinned when most contacts were unanswered |
| `TRY_ALTERNATIVE_DONOR` | Continue with other donors; the failed donor stays excluded |
| `TRY_ALTERNATIVE_BRIDGE_GROUP` | Change bridge-group handling: `BRIDGE_FIRST` or `NON_BRIDGE_FIRST` (`TRY_BRIDGE_GROUP` is an alias) |
| `EXPAND_SEARCH_RADIUS` | Ask Matching for the next radius step (30 km → 80 km → region-wide) |
| `HUMAN_COORDINATOR` | Stop automation; a coordinator takes over |
| `BLOOD_BANK_ESCALATION` | Stop automation; recommend that a person contacts the institutional blood bank |

`RecoveryActionType` (persisted `RecoveryAction.action_type`, and the cascade's `HealingDecision.action`) is
unchanged; `PERSISTED_ACTION` maps every plan action onto it, so the vocabularies cannot drift.

### 11.3 Policy priority (first match wins)

| # | Rule | Condition | Action |
|---|---|---|---|
| P1 | Safety limit | last allowed wave, `MAX_RECOVERY_ATTEMPTS` used, or `HUMAN_ESCALATION_CONTACTS` donors contacted | escalate (blood bank if CRITICAL urgency, else coordinator) |
| P2 | Pool exhausted | no eligible candidate left | `EXPAND_SEARCH_RADIUS`, or escalate at the widest radius |
| P3 | Critical stall | CRITICAL urgency + CRITICAL severity after `CRITICAL_ESCALATION_WAVES` failed waves | `BLOOD_BANK_ESCALATION` |
| P4 | Bridge-group failure | autopsy pattern `BRIDGE_GROUP_FAILURE`, non-members remain | `TRY_ALTERNATIVE_BRIDGE_GROUP` (non-members first) |
| P5 | Channel response failure | pattern `CHANNEL_RESPONSE_FAILURE`, switches left, a stronger channel exists | `SWITCH_CHANNEL` |
| P6 | Local pool failing | pattern `LOCAL_POOL_FAILURE`, 3 failed waves, or fewer non-fatigued candidates than a wave | `EXPAND_SEARCH_RADIUS` |
| P7 | Repeated failed waves | second failed wave, bridge members remain | `TRY_ALTERNATIVE_BRIDGE_GROUP` (members first) |
| P8 | Several failures, enough candidates | ≥ 2 failures, ≥ 2 waves' worth of usable candidates, size below limit | `INCREASE_WAVE_SIZE` |
| P9 | Isolated failure | one donor-level failure | `TRY_ALTERNATIVE_DONOR` |
| P10 | Default | otherwise | `RE_RUN_MATCHING` |

A request with nothing outstanding gets `NO_CHANGE` (rule P0) before any rule runs. Every plan also lists up
to three **fallback actions**: the levers that are still inside the limits, in policy order, ending with the
escalation. Simulated calls are the strongest channel (reply factor 1.15), so a channel switch always moves
*to* calls; when calls already failed the engine says so and widens the wave instead.

### 11.4 Recovery limits (configurable constants in `self_healing.py`)

`MAX_WAVE_SIZE = 6` · `MAX_RADIUS_STEP = 2` (region-wide) · `MAX_RECOVERY_ATTEMPTS = 4` ·
`MAX_CHANNEL_SWITCHES = 1` · `HUMAN_ESCALATION_CONTACTS = 20` · `CRITICAL_ESCALATION_WAVES = 3` ·
`HIGH_FATIGUE_SCORE = 60`. Plans never exceed them (`apply` clamps again), so automation always ends in
`HUMAN_COORDINATOR` or `BLOOD_BANK_ESCALATION` rather than retrying indefinitely.

### 11.5 Recovery plan and explainability

`RecoveryPlan`: `request_code`, `source` (SIMULATED / RECORDED), `wave_number`, `trigger {pattern, severity}`,
`urgency`, `autopsy_recommended`, `primary_action`, `fallback_actions`, `rule_id` / `rule_name` /
`rule_strength`, `reason`, `evidence` (strings; no donor identifiers), `current_state` snapshot, `changes`
(only the settings that change: channel, wave size, radius, bridge priority), `expected_effect` (always
hedged, never a promise), `requires_human_intervention`, `escalation_type`, `escalation`.
`rule_strength` is the matched rule's fixed strength averaged with the autopsy's rule confidence, capped at
0.95. It is **not** a probability of success.

### 11.6 Human escalation

When automation stops, the plan carries `requires_human_intervention = true`, `escalation_type`
(`HUMAN_COORDINATOR` or `BLOOD_BANK`) and an `EscalationSummary`: why automation stopped, the actions
attempted, donors contacted, failure counts and a recommended human action. `CascadeResult` repeats
`requires_human_intervention`, `escalation_type` and `escalation_summary`. Escalating applies nothing
automatically.

### 11.7 Matching and Failure Autopsy integration

- **Failure Autopsy**: the engine consumes `RequestAutopsy.dominant_pattern` (type, severity, confidence) and
  records what the autopsy recommended next to what it decided; it does not repeat the analysis.
- **Matching**: plans apply as `radius_step` (the next radius), the bridge ordering of the ranking and
  `exclude_donor_codes`; the cascade always re-matches through `MatchingEngine.match`, so ranking logic is not
  duplicated and contacted/failed donors stay excluded. Candidate counts come from the wave's own match
  result; no donors are loaded for planning.
- **Cascade**: `choose_healing` / `HealingContext` remain as a compatibility adapter that restates a context as
  an engine call; the cascade itself no longer uses them.

### 11.8 Persistence

Recovery plans are part of the simulated cascade state (`CascadeWave.recovery_plan`), consistent with the
in-memory simulation: nothing is written and there are no new tables. The existing `RecoveryAction` model is
reserved for persisted runs and needs a persisted `Failure`, so it is not used yet.

### 11.9 API

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/requests/{request_code}/self-healing?seed=&response_stress=&max_waves=&wave_size=&evaluate_at=` | `SelfHealingReport`: the simulated cascade's plans per failed wave, outcome, automatic attempts, human-intervention status, and an advisory `recorded_plan` for the dataset's RECORDED failures (source RECORDED; never mixed with simulated plans) |

Deterministic and read-only; 404 for an unknown request, 409 if the set was rejected (nothing stored), 422 for invalid parameters. The same plans are embedded
in `GET /cascade` as `waves[].recovery_plan`.

### 11.10 Frontend

On `/requests/:requestCode/cascade` each failed wave now reads: **Failure → 🔍 Failure Autopsy ("What happened?")
→ 🧠 Self-Healing ("What should change?") → Action → Next wave** (for example "CALL · 3 donors"). The Self-Healing
panel shows the primary action with rule and strength, why, evidence, what will change, expected effect,
fallbacks and an "Automatic recovery available" / "Human intervention required" badge; escalations add the
`EscalationSummary`. Seed, response stress, max waves and evaluate-at controls are unchanged.

### 11.11 Safety, determinism, performance

The engine never diagnoses, decides treatment, claims availability, exposes donor identifiers in its evidence
or acts on its own in the real world; all effects are hedged ("may improve… not guaranteed") and nothing is
contacted. Identical inputs give identical plans. Planning takes well under a millisecond; a full cascade with
autopsy and recovery stays below 500 ms on the synthetic dataset.

### 11.12 Known limitations

- Thresholds and strengths are demo-calibrated, not learned; Learning does not feed back into them yet.
- A channel switch only moves to simulated calls. In the demo request most outreach already uses calls, so
  `SWITCH_CHANNEL` appears naturally on other requests (for example `REQ-00001?seed=2`: SMS → CALL, 2 → 3 donors).
- Plans are not persisted; a persisted cascade will map them onto `RecoveryAction`.
- The recorded plan is advisory and evaluated as if wave 1 were being decided today.

## 12. Learning Engine ✅

> **Learning is a deterministic, descriptive analysis layer.** It reports what the data shows, how much
> evidence supports it and where it stops. It does not train a model, does not claim causation and does not
> change any operational rule. Synthetic demonstration data — not for clinical use.

| Engine | Question it answers |
|---|---|
| Failure Autopsy | "What happened?" |
| Self-Healing | "What should change?" |
| **Learning** | **"What should be remembered?"** |

Code: `app/services/learning.py` (statistics, thresholds, insight builders, `LearningEngine`),
`app/services/learning_report.py` (simulated runs), `app/repositories/learning_repository.py` (read-only
queries), `app/schemas/learning.py`. No new tables, no migration.

### 12.1 Architecture and data sources

| Population | Source | Reached via |
|---|---|---|
| **RECORDED** | Stored rows: interactions, coordination attempts, failures, recovery actions, learning events, requests | `GET /api/v1/learning/report` |
| **SIMULATED** | In-memory Adaptive Cascade runs (seed, seed+1, …); recovery plans and autopsies embedded in each wave | `GET /api/v1/requests/{code}/learning?seed=&runs=&response_stress=` |

The two populations are never combined: separate endpoints, separate insight ids (`…-RECORDED` /
`…-SIMULATED`), separate sample sizes, a `source` and a `provenance` label on every insight. The recorded path
uses SQL aggregation (`GROUP BY` counts) and narrow column projections; it loads no ORM entities and runs no
per-donor or per-request queries. Reading a report writes nothing.

### 12.2 Capabilities

| Capability | RECORDED evidence | Notes |
|---|---|---|
| Channel effectiveness | reply and acceptance rate per channel, **donation requests only** | availability checks and follow-ups differ in purpose and in which channels carry them; pooling them compared unlike things |
| Failure patterns | stored failure categories; Failure Autopsy pattern rules applied to each request with ≥ 2 failures | pool-based patterns need a candidate-pool snapshot the dataset does not store, so they are reported as `INSUFFICIENT_DATA` historically |
| Recovery effectiveness | each recovery action joined to the recorded `RECOVERY_SUCCESS` / `RECOVERY_FAILURE` learning event that references it | an observed association, never a causal effect; coverage of recorded outcomes is reported separately |
| Donor fatigue | reply rate by number of the donor's earlier contacts in the previous 30 days (the Donor State window) | aggregate only; confounded by selection |
| Coordination bottlenecks | reply time per channel, back-to-back no-responses, time to secure, share secured after required-by, recovery-route mix and escalations, recorded pool exhaustion | descriptive |
| Data sufficiency | every insight's strength, plus an explicit list of capabilities without suitable evidence | |

### 12.3 Evidence strength

Based on the **smallest compared group**, with transparent thresholds (`THRESHOLDS` in the report):

| Smallest group | Label |
|---|---|
| < 10 | `INSUFFICIENT_DATA` (shown, no conclusion drawn, "collect more data") |
| 10–29 | `LOW` |
| 30–99 | `MODERATE` |
| ≥ 100 | `HIGH` |

Associations that are observational by nature (recovery effectiveness, donor fatigue, failure patterns) are
**capped at `MODERATE`** whatever the sample size. A group below 10 is displayed but excluded from comparisons.
Proportions carry a 95 % Wilson interval; two groups "clearly differ" only if their intervals do not overlap.
`HIGH` means "a large synthetic sample", never "effective in the real world". Every insight states its
numerator, denominator, sample size, time window (taken from the data, never the wall clock), reason and limits.

### 12.4 Supported and unsupported conclusions

- **Supported:** descriptive rates and counts with their denominators; which channel replied more often in these
  records; which failure categories and patterns recur; what followed each recovery action; where time was lost.
- **Not supported, never made:** that a channel or recovery action *caused* a better outcome; that any result
  holds for real donors or hospitals; anything medical; donor-level conclusions (no donor identifiers appear in
  any insight); that donors can be contacted more often.

### 12.5 Recommendations and configuration

Recommendations are advisory text (`implemented` is always `false`). Rules: a clear difference with at least
`MODERATE` evidence yields "consider…" wording; insufficient evidence yields "collect more data"; donor fatigue
always yields "keep the existing protections unchanged".

| Setting | Default | Effect |
|---|---|---|
| `LEARNING_ADJUSTMENTS_ENABLED` | `false` | When `true`, `MODERATE`/`HIGH` recommendations additionally carry a **bounded adjustment proposal** (at most `LEARNING_MAX_ADJUSTMENT_POINTS = 5`). Nothing consumes it: matching, donor state, recovery and the cascade are unchanged either way (regression-tested) |

Applying a proposal to ranking or recovery is future work and would need its own tests; the deterministic
rules remain the fallback.

### 12.6 Safety boundaries

Learning never modifies blood-compatibility rules, medical eligibility, donation-deferral rules, donor
availability declarations, fatigue scoring or contact limits, or the Self-Healing and human-escalation limits.
There is no online training, self-modifying code or LLM. Fatigue analysis reports aggregates only and its
guidance is always "keep protections unchanged"; a higher reply rate among heavily contacted donors is
explicitly labelled as probably selection, not a reason to contact more.

### 12.7 Frontend

`/learning`: a persistent synthetic-data banner, then **Recorded data** (population and provenance, data
sufficiency, insights by capability with bars, sample sizes and strength, a "why and limits" disclosure,
recommendations marked "Recommendation only · Not implemented", thresholds) and a visually separate
**Simulation** section with request, first seed, runs pooled and response-stress controls.

### 12.8 Known limitations

- The data is generated: its patterns reflect the generator, not donors. Large samples do not change that.
- Channel and recovery comparisons are not randomised; recoveries differ in the failures they answered.
- The recovery link relies on the recorded learning event; the 21 recoveries without one are excluded, not guessed.
- Fatigue uses recorded interactions only; the stored donor fatigue scores are uniformly low and add no contrast.
- Simulated insights from a few runs are mostly `LOW` or `INSUFFICIENT_DATA`; fatigue is not assessable in simulation.
- Pool exhaustion and local-pool patterns cannot be assessed on recorded data (no pool snapshot).
- Reports are computed on demand and not persisted; they are not trended over time.

## 13. Notification foundation ✅ (Phase 10A)

> **Phase 10A records notifications; it does not send them.** There is no provider, no network call and no
> messaging client. A successful API response proves nothing about delivery. Demonstration software with
> synthetic data — not for clinical use.

Scope of this phase: the persistent model, the service and the REST API. The demo provider and the cascade
events that use it arrived in Phase 10B ([section 14](#14-demo-messaging-provider--phase-10b)); the Notification
Center UI and live SMS are still to come.

Code: `app/models/notification.py`, `app/schemas/notification.py`, `app/repositories/notification_repository.py`,
`app/services/notifications.py`, `app/api/routes/notifications.py`.

### 13.1 Data model (`notifications`)

| Field | Notes |
|---|---|
| `notification_code` | Public id, `NTF-` + 12 hex characters (unique). The numeric primary key is never exposed |
| `event_type` | `DONOR_OUTREACH`, `DONOR_ACCEPTED`, `REQUEST_UPDATE`, `REQUEST_FULFILLED`, `RECOVERY_ACTION`, `ESCALATION`, `SYSTEM_NOTICE` |
| `recipient_role` | `DONOR`, `PATIENT`, `COORDINATOR`, `SYSTEM` |
| `recipient_ref` | Donor code (`DON-00001`), patient code (`PAT-0001`) or a short coordinator label; null for `SYSTEM` |
| `blood_request_code` | Optional request code |
| `channel` | `IN_APP`, `SMS`, `WHATSAPP` (a new enum: the cascade's `InteractionChannel` means simulated donor outreach) |
| `mode` | `DEMO` (the only creatable value) or `LIVE` (reserved) |
| `status` | `QUEUED`, `SIMULATED`, `SENT`, `DELIVERED`, `FAILED`, `CANCELLED` |
| `title` (≤ 160), `body` (≤ 500) | Operational text only |
| `read_at` | In-app read state; null = unread |
| `provider_message_id`, `failure_code`, `failure_message` | Reserved for a future provider; always null today |
| `idempotency_key` | Optional, unique |
| `created_at`, `updated_at` | Operational clock (`operational_now`), so demos and tests are deterministic |

Recipients and requests are referenced **by public code, not foreign key**: a reseed regenerates internal ids,
and notifications must neither dangle nor be cascade-deleted. Two database `CHECK` constraints back up the
service: `demo_never_delivered` (`NOT (mode = 'DEMO' AND status IN ('SENT','DELIVERED'))`) and
`provider_id_only_live` (a provider message id requires `LIVE`).

### 13.2 Status definitions

| Status | Meaning | Possible in Phase 10A |
|---|---|---|
| `QUEUED` | Waiting to be processed; nothing has been attempted | yes (creatable) |
| `SIMULATED` | Demo mode: recorded as if sent; **no external message exists** | yes (default) |
| `SENT` | The provider accepted the request (LIVE only): not a delivery confirmation | only via the controlled test send (section 15) |
| `DELIVERED` | A provider confirmed delivery (LIVE only) | no |
| `FAILED` | The provider definitely rejected it; safe failure code and message | only via the controlled test send |
| `UNCERTAIN` | LIVE only: the provider call may or may not have gone through; never resent automatically | only via the controlled test send |
| `CANCELLED` | Withdrawn before processing | not creatable yet |

Every response carries a `delivery_note` that states what the status does and does not mean.

### 13.3 API (`/api/v1/notifications`)

| Method | Path | Behaviour |
|---|---|---|
| GET | `/notifications` | Paginated (`page`, `page_size` ≤ 100), newest first. Filters: `recipient_role`, `recipient_ref`, `request_code`, `channel`, `mode`, `status`, `unread_only`. Invalid values → 422 |
| GET | `/notifications/summary` | `total`, `by_status` (zero-filled), `by_mode`, `by_channel`, `unread_in_app`; same filters |
| GET | `/notifications/{notification_id}` | 404 if unknown, 422 if malformed |
| POST | `/notifications` | Records a DEMO notification (`SIMULATED` default, or `QUEUED`). 201 when created; 200 with the original on an idempotent repeat; 409 if the key was used for a different notification; 422 for invalid input, `LIVE` mode, delivery statuses, unknown donor/patient/request |
| PATCH | `/notifications/{notification_id}/read` | In-app only (409 otherwise or if cancelled); repeating keeps the first `read_at` |

Content rules (422): no phone numbers or email addresses; a donor message may mention no other donor and no
patient; a patient message may mention no donor and no other patient. Coordinator and system messages are
operational and may reference codes. Bodies are not for medical information and the API stores none.

### 13.4 Database and migration handling

The project has no migration tool. `init_db()` runs `Base.metadata.create_all` at startup, which **creates only
missing tables**, so the `notifications` table appears on the next start and nothing else changes: no drop,
reset, reseed or `ALTER`. This was verified on a copy of the existing database (all ten dataset tables kept
identical row counts; `notifications` was added). A future move to a migration tool (for example Alembic) would
start from this table definition. `clear_dataset` (used by the seed) skips `notifications`, so regenerating the
synthetic dataset never deletes notification records.

### 13.5 Demo-mode limitations and security

- Nothing is sent, so `SENT` and `DELIVERED` never occur, and an API success is not evidence of delivery.
- **There is no authentication or authorisation.** Anyone who can reach the API can list, create and mark
  notifications. The endpoints are demo-only and not production-secure; a real deployment needs identity,
  role-scoped access (a donor must only ever see their own notifications) and rate limiting first.
- The content rules reduce accidental disclosure; they are not a substitute for access control.
- No credentials or secrets are stored or required; no new configuration or environment variable was added.

### 13.6 Future provider-based messaging

The provider interface and **simulated provider** now exist (Phase 10B, section 14). A later phase adds an optional **live SMS provider** (`LIVE`: `SENT`, `DELIVERED`,
`FAILED`, with `provider_message_id` and credentials read from the environment, never the database), plus a
Notification Center in the frontend and event creation from the cascade, recovery and escalation workflows. LIVE
creation will need explicit configuration, consent handling and recipient verification before it is enabled.

## 14. Demo messaging provider ✅ (Phase 10B)

> **The cascade is a simulation, so these notifications are simulated too.** The demo provider records a
> notification as `DEMO` / `SIMULATED`. Nothing is sent, nobody is contacted, no donor response is implied and
> there is no external call. Synthetic demonstration data — not for clinical use.

Code: `app/services/notification_provider.py` (interface and demo provider),
`app/services/coordination_notifications.py` (event templates and the `CoordinationNotifier`),
`POST /api/v1/requests/{request_code}/cascade/notifications`. It reuses the Phase 10A notification service,
table and idempotency mechanism; nothing was duplicated and no schema changed.

### 14.1 Provider interface

```python
class NotificationProvider(Protocol):          # runtime-checkable
    name: str; mode: NotificationMode
    def deliver(self, request: NotificationCreate) -> ProviderResult: ...

ProviderResult(outcome: RECORDED | DUPLICATE | REJECTED, notification: NotificationOut | None, error: str | None)
```

`DemoMessagingProvider` is the only implementation. Whatever the request asks for, it records `mode=DEMO`,
`status=SIMULATED` (never `QUEUED`, `SENT` or `DELIVERED`), never sets a provider message id and imports no
network or messaging client. It delegates to `NotificationService.create`, so privacy validation, reference
checks and idempotency are exactly Phase 10A's. An unknown reference or an idempotency-key conflict comes back
as `REJECTED` with the reason instead of raising, so a workflow can inspect it. `RECORDED` means "a simulated
record was stored", never "delivered". A live provider would implement the same interface in a later phase.

### 14.2 When notifications are created

Only on an explicit **POST**. Viewing the cascade, matching, autopsy, self-healing, learning, twin or donor
reports (all GET) never creates a notification (tested). The POST runs the same deterministic simulation as
`GET /cascade` with the same parameters (`evaluate_at`, `max_waves`, `wave_size`, `seed`, `response_stress`) and
records its events. `build_notifications` is a pure function of the finished `CascadeResult`: the notification
layer observes the simulation and cannot change seeds, wave size, rankings, autopsies, recovery decisions or
learning insights (verified by comparing every report before and after).

| Event | Type | Recipient | When |
|---|---|---|---|
| Donor contact initiated | `DONOR_OUTREACH` | the contacted donor | each donor in each wave |
| Coordination started | `REQUEST_UPDATE` | patient | wave 1 only; generic status, no promises |
| Wave failed | `REQUEST_UPDATE` | coordinator | each wave that does not secure the requirement |
| Recovery selected | `RECOVERY_ACTION` | coordinator | each automatic Self-Healing plan |
| Escalation | `ESCALATION` | coordinator | automation stopped (human coordinator or blood bank); replaces the recovery notice for that wave |
| Requirement secured | `REQUEST_FULFILLED` | coordinator and patient | simulation reached the required units |

Exhausted candidate pools surface through the wave-failed, recovery (widen the search) and escalation
notices, which carry the engine's own reason. Request-status changes are **not** emitted: a simulation does not
change a request's stored status. `DONOR_ACCEPTED` exists in the vocabulary but is not emitted. A simulated call
has no notification-channel equivalent, so call outreach is recorded as `IN_APP` and the text says "call"; SMS
maps to `SMS` and app messages to `IN_APP`.

### 14.3 Message content

Every body starts with "Synthetic demonstration, not for clinical use." and every title with `[DEMO]`. Donor
messages say that request code X reached wave N in a simulation, name the simulated channel, state that no real
message was sent to any phone and that nothing is being asked of the donor; they carry no patient, other-donor,
phone or email detail. Patient messages are generic ("coordination is in progress" / "the simulation reached a
secured outcome") and disclaim availability and clinical outcome. Coordinator messages name the request code and
give the failure counts and pattern, the recovery decision with its reason, or the escalation with a concise
next action. Messages contain no dates or long digit runs, so the Phase 10A privacy validation accepts them; a
template that ever broke those rules is reported as `REJECTED` rather than stored.

### 14.4 Idempotency and distinct simulations

Key: `<request>:<simulation id>:<event>:w<wave>:<recipient>`; the coordinator recipient is the literal
`COORDINATOR`. The **simulation id** (`SIM-` plus 12 hex characters) is a hash of the request code and every
simulation parameter, so two simulations that can differ never share a key, and repeating one never duplicates:
the second POST returns 200 with `created=0` and every item `DUPLICATE`. Notification timestamps use the
operational clock, so they are deterministic rather than simulation times.

### 14.5 API

| Method | Path | Behaviour |
|---|---|---|
| POST | `/api/v1/requests/{request_code}/cascade/notifications` | Same query parameters as `GET /cascade`. 201 if any notification was created, 200 if all already existed, 404 for an unknown request, 422 for invalid parameters. Returns `simulation_id`, counts (`created`, `duplicates`, `rejected`), per-event outcomes and notification ids |

Demo-only and, like all Phase 10A endpoints, **unauthenticated**.

### 14.5a Reliability (Phase 10D)

- **All-or-nothing.** A simulation's notifications are stored in one transaction: each one is staged
  (`commit=False`) and the set is committed only if every notification was recorded or already existed. A rejection (an
  idempotency key already used for a different notification, an unknown reference, a template that breaks the privacy
  rules) or a database error rolls the whole set back and the endpoint answers **409** with the reasons (an unexpected
  error propagates as a 500); a failure never leaves a partial event set, and the same simulation can then be recorded
  completely.
- **Event audit.** Across 72 simulations (three requests of different urgency, eight seeds, three stress and wave
  settings; fulfilled, human-coordinator and blood-bank outcomes) a test checks that donor outreach equals contacts,
  failed-wave notices equal unfulfilled waves, recovery notices equal automatic plans, exactly one escalation per
  unfulfilled run and none otherwise, exactly one fulfilment notice per recipient when secured, and patient messages
  only for "in progress" and, when reached, "secured". No event the simulation cannot substantiate is emitted, and no
  gap was found, so no event type was added.
- **Separation.** Simulation events are never mixed with stored dataset events and a simulation never changes a stored
  request status (tested). Records survive a synthetic-data reseed, and re-running the same simulation afterwards
  creates nothing new.

### 14.6 Limitations

- Everything is simulated: no real donor is contacted, no phone is involved and no response is implied.
- Not built yet: any live SMS or WhatsApp provider, notifications from persisted (non-simulated) workflow events,
  and automatic dispatch; dispatch requires an explicit POST. (The in-app Notification Center arrived in Phase 10C, below.)
- Message volume is one notification per contacted donor per wave, plus a handful of coordinator and patient
  notices; there is no batching, throttling or per-recipient preference handling.

### 14.7 Notification Center (Phase 10C)

`/notifications` (nav item "Notifications"; `pages/NotificationsPage.tsx`, `components/notifications/`,
`services/notificationService.ts`, `types/notifications.ts`) is a frontend over the existing endpoints only:
`GET /notifications`, `GET /notifications/summary`, `PATCH /notifications/{id}/read` and
`POST /requests/{code}/cascade/notifications` (plus `GET /requests?search=` for the request finder). No backend
event type, authentication or provider was added.

- **Honest display.** A persistent banner and every row state "DEMO / SIMULATED: no real SMS, WhatsApp message or
  phone notification was sent". Statuses are the API's values; demo channels read "SMS (simulated)". The
  "Sent or delivered" card is derived from the backend's `SENT` + `DELIVERED` counts (zero in demo mode) and says
  why; a successful response is never presented as delivery.
- **Summary** cards (total, unread, simulated, queued, sent or delivered) come from the unfiltered summary endpoint.
- **Inbox:** 10 per page, filters for recipient role, status, channel, request code and unread only (all
  supported by the API and kept in the URL); there is no event-type filter because the backend has none. Unread
  in-app rows are visually distinct; SMS/WhatsApp records have no read state. Rows expand to the full title and body,
  the delivery note, ids, timestamps and any safe failure details.
- **Mark as read** calls the PATCH endpoint; the UI changes only after the API confirms, then reloads the list and
  summary. There are no bulk-read or delete actions.
- **Demo action.** A separate card explains that it runs a deterministic simulation and records simulated
  notifications, shows the selected request and settings (seed, response stress, max waves, wave size), disables
  and marks itself busy while running, and shows the backend's actual result (created / duplicate / rejected, per
  event). A repeat reports "nothing new was recorded". 404, 422, server and network errors are shown with the backend's
  detail. Nothing runs on page load.
- **States:** loading, empty (with a hint to use the demo action), error with Retry; the previous data stays visible
  while a refresh is in flight. The list is a compact card layout, so it works from 390 to 1440 px.
- The main navigation was tightened (smaller padding below `xl`) so eight items fit at 1024 px.

Request finder (Phase 10D): the demo action no longer loads a fixed list. A search box queries `GET /requests?search=`
(eight matches at a time, debounced), starts on `DEMO-REQUEST-001` looked up for real, shows only the request code,
urgency, status, blood group and city (no patient identifiers), reports "No request matches…" for an unknown code, and
keeps the simulation button disabled until a real request is selected. Enter picks the best match and never starts the
simulation.

Limitations: there is no frontend
test framework in the project, so validation is a scripted headless-browser run; the page has no authentication,
like the API.

## 15. Live SMS provider ✅ (Phase 10E.1)

> **DEMO is the default and sends nothing.** Live sending is a controlled, single-message test through Twilio, possible
> only when the backend is explicitly configured `MESSAGING_MODE=LIVE` **and** every safety check passes for a real
> person who agreed to receive test messages. It is never triggered by viewing a page, a report or the cascade, and it
> never goes to a synthetic donor or patient. Not for clinical use; no authentication exists.

Code: `app/services/live_sms.py` (`TwilioSmsProvider`, `RecipientAuthorizer`, `LiveSmsSender`, templates, error
classification), `app/models/messaging.py` (`TestRecipient`), `app/db/test_recipients.py` (operator tool),
`POST /api/v1/notifications/test-sms`. `DemoMessagingProvider` and every demo workflow are unchanged.

### 15.1 Demo versus live

| | DEMO (default) | LIVE |
|---|---|---|
| Selected by | `MESSAGING_MODE=DEMO` (or unset) | `MESSAGING_MODE=LIVE` with valid Twilio settings |
| Records | `mode DEMO`, status `SIMULATED` | `mode LIVE`, status `QUEUED` then `SENT`, `FAILED` or `UNCERTAIN` |
| Provider message id | never | the real Twilio SID, only after a successful send request |
| Cascade / event notifications | recorded by the demo provider | **still demo**: workflows never use the live provider |
| `DELIVERED` | impossible (database constraint) | impossible in this phase: needs a trusted status callback, which is not implemented |

### 15.2 Configuration (backend environment only)

| Variable | Default | Notes |
|---|---|---|
| `MESSAGING_MODE` | `DEMO` | `DEMO` or `LIVE` |
| `TWILIO_ACCOUNT_SID` | empty | required in LIVE; must look like `AC` + 32 hex characters |
| `TWILIO_AUTH_TOKEN` | empty | required in LIVE; held as a secret string, never printed |
| `TWILIO_FROM_NUMBER` | empty | required in LIVE; your Twilio sender, E.164 (`+15551230000`) |
| `TWILIO_STATUS_CALLBACK_URL` | empty | optional https URL passed to Twilio; no webhook handler exists yet |

Startup fails (before the server serves anything) if LIVE is selected with missing or malformed values; the error names
the **settings**, never their values (`hide_input_in_errors`). Credentials live in `backend/.env` (git-ignored; only
`.env.example`, with empty placeholders, is committed). They are never sent to the frontend, returned by the API,
logged, or included in exception text; `TwilioConfig` redacts itself in `repr`. A test scans the source, docs and any
built frontend bundle for credential shapes.

### 15.3 Configure Twilio locally

1. Install the backend dependencies (`pip install -r backend/requirements.txt`; the official `twilio` SDK was added).
2. Create `backend/.env` (never commit it):
   ```
   MESSAGING_MODE=LIVE
   TWILIO_ACCOUNT_SID=<your Account SID>
   TWILIO_AUTH_TOKEN=<your Auth Token>
   TWILIO_FROM_NUMBER=<your Twilio number in E.164>
   ```
3. Restart the backend. If a value is missing or malformed it refuses to start and names the setting.
4. A Twilio **trial** account can only message numbers verified in the Twilio console, and prefixes its messages.
   Treat any credential that has been shared in chat, email or a screenshot as exposed: rotate the Auth Token in the
   Twilio console.

### 15.4 Authorise a test recipient, then send once

Recipients are registered by an operator on the machine running the backend; there is deliberately no API for it (the
prototype has no authentication, so an open endpoint would let anyone authorise a send to any phone).

```
python -m app.db.test_recipients add --label "Project owner" --phone +15551230000 \
    --consent "Agreed by email on <date> to receive Carbon Copy test SMS" --verified
python -m app.db.test_recipients list              # numbers are masked
python -m app.db.test_recipients opt-out TR-XXXXXXXX
```

Only register a person who has really agreed, and pass `--verified` only after confirming the number is theirs. Then
one controlled send:

```
POST /api/v1/notifications/test-sms
{"recipient_code": "TR-XXXXXXXX", "template_id": "CONNECTIVITY_TEST", "idempotency_key": "first-test-0001",
 "blood_request_code": "DEMO-REQUEST-001", "confirm_live_send": true}
```

`blood_request_code` is optional context and must exist. The client never supplies a phone number, free text or a
list: it names a registered recipient and an approved template (the only text is the connectivity-test message).

### 15.5 Safety checks (all server-side, all before anything is sent)

LIVE mode configured (else 409 `LIVE_MODE_DISABLED`) · explicit `confirm_live_send: true` · recipient exists as a
registered test recipient (403 `UNKNOWN_RECIPIENT`) · valid E.164 number (`INVALID_PHONE`) · not opted out
(`OPTED_OUT`, suppression always wins) · consent recorded (`CONSENT_MISSING`) · verified by an operator
(`RECIPIENT_NOT_VERIFIED`) · exactly an approved template (`MESSAGE_NOT_APPROVED`) · request context exists
(`UNKNOWN_REQUEST`) · fewer than 5 attempts to that recipient (429 `SEND_LIMIT_REACHED`) · idempotency key present.
A refused request creates no record and makes no provider call. Synthetic donor and patient records are never
recipients: they hold no real number and no consent, and the endpoint accepts only `TR-` codes.

### 15.6 Status versus delivery

`SENT` means **the provider accepted the request** (it carries Twilio's real message SID). It does not mean the
message reached a phone. `FAILED` is a definite rejection (a stable `TWILIO_<code>` failure code and a generic message;
the provider's own text, which can contain the number, is never stored). `UNCERTAIN` is a timeout, a server error or an
unusable response: the message may or may not have been sent. `DELIVERED` cannot be set by any code path. Responses
include `provider_accepted` and `delivery_confirmed` (always `false`).

### 15.7 Idempotency and failure limits

A LIVE row is committed as `QUEUED` under the unique idempotency key **before** the provider is called, so of two
concurrent identical submissions only one inserts and sends (tested with eight threads on separate database
connections). The provider call has a hard timeout and no automatic retries. A repeat of a key returns the stored record
and never calls the provider again, whatever its status; retrying after `FAILED` or `UNCERTAIN` needs a new key chosen on
purpose. Limits: exactly-once delivery cannot be guaranteed across a crash or network failure. If the process dies after
the provider accepted but before the outcome is saved, the record stays `QUEUED` and must be checked against the
provider's logs; it is never resent automatically. Timestamps use the operational clock.

### 15.8 Before sending beyond a controlled test

Check Indian telecom rules (TRAI/DLT registration of sender ID and message templates, scrubbing, quiet hours),
Twilio's regional permissions and sender registration, your account restrictions, and obtain and record each
recipient's consent. None of that is implemented here. Authentication and authorisation are still absent: anyone who can
reach the API can request a test send to an already-registered recipient (bounded by the per-recipient limit), so keep
LIVE mode off any network you do not control.

Not implemented: delivery-status webhooks, bulk outreach, WhatsApp, sending to donors or patients.

## 16. Core future services 🗺️

Each engine is a plain Python class in `app/services/` (or a sub-package once it grows), constructor-injected,
with no FastAPI or HTTP dependencies. Signatures below are the intended contracts; names may be refined during
implementation. All engines are deterministic unless stated otherwise.

### Digital Twin Engine ✅
Implemented: see [section 6](#6-living-digital-twin-engine-). Consumers call
`DigitalTwinService.build(patient_code)` or `.request_context(request_code)`.

### Donor State Engine ✅
Implemented: see [section 7](#7-donor-state-intelligence-engine-). Consumers call
`DonorStateEngine.assess(donor_code)`, `.assess_for_request(donor_code, request_code)` or the batched
`.assess_donors(donors, as_of, request)`.

### Matching Engine ✅
Implemented: see [section 8](#8-matching-engine-). Consumers call
`MatchingEngine.match(request_code, limit, include_excluded, evaluate_at)`.

### Adaptive Cascade Engine ✅ (simulation)
Implemented as a deterministic in-memory simulation: see [section 9](#9-adaptive-cascade-engine-simulation-).
`AdaptiveCascadeEngine.simulate(request_code, evaluate_at, max_waves, wave_size, seed, response_stress)`.
Persisted runs will build on it once the Failure Autopsy, Self-Healing and Learning engines exist.

### Failure Autopsy Engine ✅
Implemented: see [section 10](#10-failure-autopsy-engine-). Consumers call
`FailureAutopsyEngine.analyze_request(request_code)`, `.analyze_failure(request_code, failure_code)`
(both RECORDED) or `.analyze_simulated(request_code, observations, context)` (SIMULATED, used by the
Adaptive Cascade). It recommends a `RecoveryRecommendation`; it never decides or executes recovery —
that stays the Self-Healing hook's job, below.

### Self-Healing Engine ✅
Implemented: see [section 11](#11-self-healing-engine-). `SelfHealingEngine.plan(request_code, state, autopsy)`
returns a `RecoveryPlan`; `SelfHealingEngine.apply(plan, settings)` applies its safe changes. The Adaptive Cascade
calls both and re-matches.

### Learning Engine ✅
Implemented as a deterministic, read-only analysis layer: see [section 12](#12-learning-engine-). `LearningEngine.recorded_report()` and `.simulated_report(runs, seeds)` return evidence-backed insights; bounded adjustment proposals exist behind `LEARNING_ADJUSTMENTS_ENABLED` but nothing applies them yet.

### Messaging Engine
Partly built: the notification record, service and API (Phase 10A, [section 13](#13-notification-foundation--phase-10a)) and the demo provider with cascade-driven events (Phase 10B, [section 14](#14-demo-messaging-provider--phase-10b)); live providers and the Notification Center do not exist.
Composes and (simulates) sending outreach.
```python
compose(template_id, context, use_ai: bool = False) -> OutreachMessage
send(message) -> DeliveryResult     # simulated channels only; never contacts real people
```
Templates are the default; the AI layer may draft wording, which is still sent through the same simulated channel.

---

## 17. Data flow

```
                  ┌──────────────────────────── Frontend (React) ───────────────────────────┐
                  │  pages → hooks → services/apiClient ── HTTP/JSON ──┐                      │
                  └────────────────────────────────────────────────────┼──────────────────────┘
                                                                       ▼
 FastAPI routes ─► dependency injection ─► Services / Engines ─► SQLAlchemy session ─► SQLite
                                               │
                                               └─► AIProvider (optional, advisory text only)
```

Coordination flow for one blood request (**original plan; the built system differs: Learning is advisory and does not update the twin or donor state, see section 12; the verified walkthrough is [demo-runbook.md](demo-runbook.md)**):

1. A `blood_request` is created, either manually or from the twin's `project_next_requirement`.
2. Donor State Engine assesses donors → Matching Engine produces ranked `CandidateMatch`es.
3. Adaptive Cascade plans waves and the Messaging Engine sends (simulated) outreach; each contact is a `donor_interaction`.
4. On success: the outcome is recorded → Learning Engine → twin and donor state are updated.
5. On failure: Failure Autopsy writes a `failure_report` → Self-Healing writes a `recovery_action`
   → the cascade resumes on the new pathway → the eventual outcome feeds Learning.
6. The frontend shows each step; the AI layer can explain any step in natural language.

---

## 18. Demo scenario

A scripted, reproducible walkthrough for the jury, using synthetic data only. **This is the original script; the current, verified walkthrough (with the exact donors, waves and notification counts) is [demo-runbook.md](demo-runbook.md).**

1. **Overview.** Platform status and scale: 6,946 donors, 80 patients and their bridge groups, 320 requests,
   7,240 historical interactions.
2. **The patient.** Open the Living Digital Twin of a synthetic recurring patient with a less common blood group.
   Next transfusion projected in 4 days; the bridge group has 9 donors.
3. **Donor intelligence.** Ranked candidates with score breakdowns: one donor excluded by the demo eligibility
   interval, one deprioritised for fatigue (contacted three times this month).
4. **Cascade, wave 1.** The top three bridge-group donors are contacted (simulated). Two do not respond; one declines
   because of travel distance.
5. **Failure Autopsy.** The attempt is classified `DISTANCE_OR_LOGISTICS` with `NO_RESPONSE` as a contributing factor,
   with the interactions shown as evidence. The AI layer narrates the report for the coordinator.
6. **Self-Healing.** Instead of restarting the same search, the system switches pathway: compatible donors outside
   the bridge group within a smaller radius, contacted by phone rather than SMS.
7. **Success.** A donor confirms. The outcome is recorded.
8. **Learning.** The twin now prefers phone outreach for this patient, and the non-responding donors' reliability
   is adjusted. The next request for this patient starts from the improved pathway.

Every screen keeps the notice visible: synthetic demonstration data, not for clinical use.

### Seeded demo record: `DEMO-REQUEST-001`

The seed always contains one fixed, easy-to-find scenario (retrieve it with
`DatasetRepository.get_blood_request_by_code("DEMO-REQUEST-001")`; a dedicated endpoint comes later):

| Step | Record |
|---|---|
| Patient | `PAT-0001` "Meera S.", B−, Hyderabad, HIGH urgency, transfusion every 21 days, bridge group `BG-0001` |
| Request | `DEMO-REQUEST-001`: 1 unit B−, status `FULFILLED`, plus broadcast availability checks |
| Attempt 1 | Donor `DON-00001` contacted by simulated SMS + follow-up → **no response** → `FAILED` / `NO_RESPONSE` |
| Failure | Category `NO_RESPONSE`, severity `HIGH`, recommended action: next donor, prefer a phone call |
| Recovery | `ALTERNATIVE_DONOR` → target `DON-00002`, status `COMPLETED` |
| Attempt 2 | Donor `DON-00002` contacted by simulated call → **accepts**, confirmation sent → `SUCCESS` |
| Learning | `NO_RESPONSE` (negative), `RECOVERY_SUCCESS` (positive), `SUCCESSFUL_MATCH` (positive) |

`DON-00001` and `DON-00002` are reserved for this scenario and do not appear in any other request.
