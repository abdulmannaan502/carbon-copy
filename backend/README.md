# Carbon Copy API

FastAPI backend for the Carbon Copy prototype. See [`../docs/architecture.md`](../docs/architecture.md) for the full design.

## Setup (Windows PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

## Seed the synthetic dataset

```powershell
python -m app.db.seed              # default seed 20261008
python -m app.db.seed --seed 42    # another reproducible dataset
```

Idempotent: deletes the synthetic dataset's rows and re-inserts the full dataset in one transaction (the operational
`notifications` and `test_recipients` tables are preserved). Do not run it needlessly on a database you are about to demo.
Synthetic demonstration data, not for clinical use.

## Run

```powershell
uvicorn app.main:app --reload --port 8000
```

- Health: http://localhost:8000/health
- System status: http://localhost:8000/api/v1/system/status
- Dataset counts: http://localhost:8000/api/v1/system/dataset-stats
- Lists (`?page=1&page_size=20`): `/api/v1/patients`, `/api/v1/donors`, `/api/v1/bridge-groups`, `/api/v1/requests`
- API docs: http://localhost:8000/docs

## Test

```powershell
pytest
```

Tests use an in-memory SQLite database and never touch `carbon_copy.db`.

## Layering

| Layer | Folder | Rule |
|---|---|---|
| HTTP | `app/api/routes` | Thin handlers: call a service, return a schema |
| Wiring | `app/api/deps.py` | Builds services and injects settings, DB session, AI provider |
| API contracts | `app/schemas` | Pydantic models for every request/response |
| Business logic | `app/services` | No FastAPI imports; collaborators passed via constructor |
| Data access | `app/repositories` | SQLAlchemy queries; services call these instead of building queries |
| Persistence | `app/models`, `app/db` | ORM models, enums, engine, sessions, synthetic generator, seed command |
| AI | `app/ai` | `AIProvider` interface; advisory text only, never operational decisions |
| Config | `app/core/config.py` | Environment variables and `.env` files |
