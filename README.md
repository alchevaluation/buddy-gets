# Buddy-Gets — Budget Core v0.1

Initial API-only proof of concept for a configurable budget matrix. No alche.val code, data, or credentials are included.

## Implemented

- Budgets with presentation currency.
- User-defined periods (date interval, label, order); removal is denied if values or FX rates exist.
- Hierarchical analytical and synthetic lines; synthetic lines roll up children or use a safe expression referencing codes, e.g. `[REV] - [COST]`.
- Independent measure buckets: `BUDGET`, `ACTUAL`, `RESERVED`, `COMMITTED`, `CONTINGENCED`, and `BLOCKED`. One balance per (line, period, measure, currency). Categories are not automatically added or transferred.
- Multicurrency values, with explicit per-period FX rates and conversion on read. Source amounts remain unchanged; missing FX rates produce an error, never a silent conversion.
- API tests for formulas, isolation between budgets, measures, conversion, and deletion protection.

## Quickstart on Windows (Anaconda Prompt)

```bat
conda activate buddygets
cd C:\Luiz\Projetos\buddy-gets
python -m pip install -r requirements.txt
set DATABASE_URL=postgresql+psycopg://buddygets_app:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:5432/buddygets
python -m uvicorn backend.app.main:app --reload
```

Alternatively, create a local `.env` at the repository root with `DATABASE_URL=...` (copy `.env.example` and replace the placeholder). `pydantic-settings` loads this file at startup. An environment variable takes precedence over `.env`. The API documentation is at `http://127.0.0.1:8000/docs`.

For isolated tests with SQLite (no PostgreSQL changes):

```bat
set PYTHONPATH=backend
python -m pytest backend/tests -q
```

## Code structure

- `backend/app/core/models.py`: SQLAlchemy entities and measure catalogue.
- `backend/app/core/calculations.py`: safe formulas and currency-aware matrix aggregation.
- `backend/app/core/config.py`: validated application settings from environment or local `.env`.
- `backend/app/core/database.py`: engine/session factory (single source of database configuration).
- `backend/app/main.py`: FastAPI routes and app factory.

## Model

`Budget` -> `Period`, `Line`; `Line` -> `Value`; `Budget` + `Period` -> `FxRate`. Values exist only on analytical lines; synthetic values are computed at query time. The query selects one measure and one presentation currency.

## Deliberately left for CC-CLI tasks

- Replace startup `create_all` with Alembic migrations.
- Editing/reordering periods and lines, deleting or reparenting lines, and formula validation at write time.
- Organization-aware authentication and tenant-level access control (the current app is **not production secure**).
- Saved composite measures, execution events and reversals, exchange-rate sets and historical valuation.
- React matrix UI, audit trail, concurrent edit control, and load testing.

## Cautions

The API uses integer IDs and is a prototype. Currency codes are syntactically validated but not matched against a currency reference table. Values have four decimal places. Do not expose this server to the public internet or enter real company data. Missing rates, circular formulas and invalid references fail explicitly. `create_all` is a development bootstrap, not a production migration strategy. No task submission text is supplied; follow the CC-CLI program's authoring requirements.
