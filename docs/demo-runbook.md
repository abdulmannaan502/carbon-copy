# Carbon Copy: jury demo runbook (release freeze)

> **Synthetic demonstration data — not for clinical use.** Carbon Copy is a prototype: no real patient or donor data, no
> medical decisions, not clinically validated. Messaging stays in **DEMO** mode: nothing is ever sent.

This is the verified walkthrough for the presentation. Everything below was checked against the running application
(see "What was verified"); steps that need a person are marked **manual**.

## 1. Pre-flight (2 minutes)

Run from `C:\WORK\Projects\carbon-copy` in PowerShell.

1. **Messaging must be DEMO.** The command prints only the mode, never a credential:
   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -c "from app.core.config import get_settings; print(get_settings().messaging_mode)"
   ```
   It must print `DEMO`. Do not set `MESSAGING_MODE=LIVE`, do not call `POST /api/v1/notifications/test-sms`, and do not run
   `python -m app.db.test_recipients`. For extra safety, leave the `TWILIO_*` lines in `backend/.env` empty while presenting.
2. **Ports 8000 and 5173 must be free.** Something else listening on 5173 is the most likely way for this demo to go wrong:
   the browser can show a different application at `localhost:5173` while Carbon Copy runs beside it.
   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 5173,8000 -ErrorAction SilentlyContinue |
     Select-Object LocalAddress, LocalPort, OwningProcess
   ```
   It should print nothing. If it lists a process, find out what it is (`Get-Process -Id <OwningProcess>`) and stop it only if
   it is yours; otherwise pick another frontend port and pass the same origin to the backend (see Troubleshooting).
3. **Do not reseed.** The database already holds the dataset. `python -m app.db.seed` rewrites it and is not needed.

## 2. Start

Backend (terminal 1):

```powershell
cd C:\WORK\Projects\carbon-copy\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend (terminal 2); `--strictPort` makes it fail loudly instead of quietly moving to another port:

```powershell
cd C:\WORK\Projects\carbon-copy\frontend
npm run dev -- --host 127.0.0.1 --strictPort
```

Open **http://127.0.0.1:5173**. (`npm run dev` without flags also works when nothing else uses the port.)

To rehearse without writing notifications into the real database, run the backend on a copy:

```powershell
Copy-Item C:\WORK\Projects\carbon-copy\backend\carbon_copy.db $env:TEMP\cc-demo.db
$env:DATABASE_URL = "sqlite:///" + ($env:TEMP -replace '\\','/') + "/cc-demo.db"
# then start uvicorn as above, in the same terminal
```

## 3. Smoke-test checklist (about 8 minutes)

| # | Do | Expect |
|---|---|---|
| 1 | Open http://127.0.0.1:8000/health | `status: ok`, `database: connected` |
| 2 | Open the dashboard `/` | Top banner "Synthetic demonstration data — not for clinical use"; System Operational; Backend and Database **Connected**; AI assistance **Not configured** (true: no AI provider is implemented, see Limitations); Data mode **Synthetic demo**; 80 patients, 6,946 donors, 80 bridge groups, 320 requests, 7,240 interactions; 576 attempts, 266 failures, 266 recovery actions, 799 learning events |
| 3 | Click **Open Living Digital Twin · PAT-0001** | Twin page for the synthetic patient with the synthetic-data label |
| 4 | Nav **Matching** (`/requests/DEMO-REQUEST-001/matching`) | HIGH urgency, B−, Hyderabad; ranked donors, top three DON-03455, DON-03010, DON-01638 (score 86); excluded donors listed with reasons |
| 5 | Open **http://127.0.0.1:5173/requests/DEMO-REQUEST-001/cascade?seed=25** (the nav "Cascade" link uses the default seed, where wave 1 simply succeeds) | Wave 1: 3 donors contacted by simulated call, no response → **Failure Autopsy** (channel response failure, HIGH) → **Self-healing decision**: increase wave size 3 → 4, by call, with evidence, expected effect and fallbacks → Wave 2: 4 donors, DON-00002 accepts → "Requirement secured in 2 waves". Below: "Recorded: what actually happened" (the dataset's own history) kept separate from the simulation |
| 6 | Nav **Learning** | Persistent synthetic-data banner; **Recorded data** and a separate **Simulation** section; sample sizes and evidence strength; "Recommendation only / Not implemented"; insufficient-data warnings where they apply |
| 7 | Nav **Notifications** | Banner "no real SMS, WhatsApp message or phone notification was sent". On the current database the inbox is empty ("There are no notifications yet") and nothing is created by opening the page |
| 8 | In **Demo action**, check the request shows `DEMO-REQUEST-001` (type a code to search), seed 25, press **Run simulation and record notifications** (**manual**: it writes simulated records) | "Recorded 12 simulated notifications for DEMO-REQUEST-001"; inbox shows rows labelled **DEMO** and **SIMULATED**; **Sent (accepted) 0** and **Delivered 0** |
| 9 | Press the button again | "Nothing new was recorded: all 12 notifications for this simulation already existed" |
| 10 | Expand a notification; filter by role/status/channel, tick Unread only, press Mark as read | Detail says no real message was sent; filters change the list and the count; the Unread card drops after the API confirms |
| 11 | Confirm labels | Every page shows the synthetic-data banner; no notification shows SENT or DELIVERED; Learning never claims real-world effectiveness |

## 4. Stop safely

Press `Ctrl+C` in the frontend terminal, then in the backend terminal. Close the terminals. Nothing else needs cleaning up; do
not delete `carbon_copy.db`. (Notifications recorded in step 8 stay in the database and are harmless synthetic records.)

## 5. What works offline

The core demo needs **no internet** once the dependencies are installed.

- **Backend:** FastAPI + SQLite on the local disk. In DEMO mode it makes no outbound network calls: the only outbound-capable
  code is the Twilio client, imported only in LIVE mode. The running backend held only loopback connections during the audit.
- **Frontend:** served by the local Vite dev server from the local `node_modules`; the source and the built bundle contain no
  external fonts, scripts or API calls. The whole browser journey was re-run with every non-local hostname made
  unresolvable and passed.
- **AI:** none is required. The AI layer is a disabled stub (`AIProvider`); every matching, eligibility, cascade, autopsy,
  self-healing and learning result is computed deterministically.
- **Needs the internet only for:** the first-time setup (`pip install`, `npm install`) and, if ever enabled, `MESSAGING_MODE=LIVE`
  (Twilio). Not used in this demo. Note: a headless Edge on the audit machine also contacted `cdn.honey.io`; that request is
  made by the browser environment itself (it also appears when loading the plain backend JSON), not by Carbon Copy.

## 6. Troubleshooting

- **The page shows another application, or Carbon Copy cannot load data.** Another process owns port 5173 (the backend only
  accepts the origins `http://localhost:5173`, `http://127.0.0.1:5173` and `FRONTEND_URL`). Free the port, or start the
  backend with `$env:FRONTEND_URL = "http://127.0.0.1:5180"` and the frontend with
  `npm run dev -- --host 127.0.0.1 --port 5180 --strictPort`, and open that address.
- **"Cannot reach the API" / Backend: Unavailable.** The backend is not running on port 8000, or the frontend origin is not allowed.
- **Notification Center shows 0 notifications.** Expected before step 8; nothing is created automatically.
- **Backend refuses to start with a message naming `TWILIO_*` settings.** `MESSAGING_MODE` is `LIVE` with missing or invalid
  values: set `MESSAGING_MODE=DEMO` (or remove the line).

## 7. Known limitations (confirmed)

- Everything is synthetic and simulated. The cascade is a simulation; "recorded" history is generated data. Learning results
  describe the dataset, not real donors, and are advisory only (nothing is applied to matching or recovery).
- No AI provider is implemented (the dashboard shows "AI assistance: Not configured"). The headline and metadata no longer claim
  "AI-powered"; the engines are deterministic and rule-based, so say that if asked.
- Live SMS code exists (Phase 10E.1), `backend/.env` currently holds Twilio credentials and the database holds one registered,
  consenting test recipient. The only thing preventing a real message is `MESSAGING_MODE=DEMO` (verified: the endpoint answers 409
  `LIVE_MODE_DISABLED`). There is no authentication anywhere in the API. Keep both services on 127.0.0.1.
- The default cascade link has no failure (wave 1 succeeds); the failure/recovery story needs `?seed=25`.
- The original plan sections 17 and 18 of `architecture.md` predate the build; this runbook is the verified script.
- Verified with a headless Edge on Windows only (1440, 1024 and 390 px emulated). Real phones, Chrome, Firefox and Safari were not tested.
- The working directory is not a Git repository, so "secrets excluded from Git" could only be checked through `.gitignore`
  (`.env`, `.env.*`, `*.db`, `dist/`, `node_modules/` are ignored; only `.env.example`, with empty placeholders, is allowed).

## 8. What was verified (Phase 11 audit)

Backend suite: 421 passed. Frontend production build: succeeded. A 32-check HTTP smoke test (health, status, dataset, patients,
request search, twin, donor state, matching, cascade, autopsy, self-healing, learning, notification create/repeat/list/filter/read,
test-SMS refusal, 404/422 handling, dataset unchanged) passed on a copy of the database. A browser journey over every demo page at
1440, 1024 and 390 px, plus main-navigation clicks, passed with no console errors or warnings, no failed requests, no horizontal
overflow, and a visible synthetic-data banner on every page, including with all external hosts unreachable. No real message was
sent and no Twilio call was made. The real database was only opened read-only.
