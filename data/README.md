# data/

> **Synthetic demonstration data — not for clinical use.**

Everything in the Carbon Copy dataset is fabricated. **No real patient or donor information, real phone numbers,
real addresses or real medical records may ever be added to this project.** Names are random combinations,
phone numbers are `SIM-PHONE-xxxxx` placeholders, coordinates are jittered around city centres, and bridge
groups are fictional organisations. Any resemblance to real people or organisations is coincidental.

## Where the dataset comes from

The dataset is generated, not stored. The generator lives with the backend so it can reuse the ORM models:

- `backend/app/db/synthetic.py`: deterministic generator (`generate_dataset(seed)`)
- `backend/app/db/seed.py`: writes it to the database

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.db.seed
```

The same seed (default `20261008`) always produces identical data. See
[`docs/architecture.md`](../docs/architecture.md#4-database-architecture-) for the full strategy.

| Entity | Count |
|---|---|
| Donors | 6,946 |
| Patients | 80 |
| Bridge groups | 80 |
| Blood requests | 320 |
| Donor interactions | 7,240 |
| Coordination attempts | 576 |
| Failures | 266 |
| Recovery actions | 266 |
| Learning events | 799 |

This folder is reserved for future static reference data and exports (`data/generated/` is git-ignored).
