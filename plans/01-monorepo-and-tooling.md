# 01 — Monorepo & Tooling

## Stack

- **NX** as the workspace orchestrator.
- **`@nxlv/python`** plugin with **UV** as the Python package manager (most
  active Python-in-NX plugin; UV is fast and matches the user's stated
  preference).
- **pnpm** as the JS package manager (NX's recommended).
- **Node 20 LTS**, **Python 3.12**.

## Directory layout

```
video-detection/
├── nx.json
├── package.json                 # pnpm workspace + nx + frontend deps
├── pyproject.toml               # root uv workspace (managed by @nxlv/python)
├── tsconfig.base.json
├── .editorconfig
├── .gitignore
├── .pre-commit-config.yaml
├── docker/
│   ├── docker-compose.yml
│   ├── docker-compose.override.yml         # local dev overrides
│   ├── postgres/
│   │   └── init.sql                        # CREATE EXTENSION vector;
│   └── worker/
│       └── Dockerfile                      # CUDA + ultralytics + insightface
├── data/                                   # gitignored; bind-mounted into containers
│   ├── videos/{inbox,processed,failed}/
│   ├── frames/
│   └── models/{yolo,insightface,classifiers}/
├── plans/                                  # this folder
├── apps/
│   ├── web/                                # React + Vite + shadcn
│   ├── api/                                # FastAPI service
│   ├── worker/                             # Celery worker(s)
│   └── ingest-watcher/                     # watchdog → Celery enqueue
├── libs/
│   ├── python/
│   │   ├── db/                             # SQLAlchemy models + Alembic
│   │   ├── ml/                             # detector/embedder/training code
│   │   ├── settings/                       # pydantic-settings shared config
│   │   └── tasks/                          # Celery task contracts + schemas
│   └── ts/
│       ├── api-client/                     # generated from OpenAPI
│       ├── ui/                             # shared shadcn-derived components
│       └── theme/                          # tailwind preset + tokens
└── tools/
    ├── scripts/                            # repo-level scripts (one-shots)
    └── openapi-codegen/                    # nx target wrappers
```

Notes:
- `apps/api`, `apps/worker`, and `apps/ingest-watcher` are separate Python
  projects (each with its own `pyproject.toml` managed by `@nxlv/python`),
  so they get independent dependency trees but all share the libs under
  `libs/python/*` via path dependencies.
- `libs/ts/api-client` is regenerated from the API's OpenAPI schema on every
  API change (see plan 04).

## NX targets (per project)

Common Python project:
- `lint` — `uv run ruff check .`
- `format` — `uv run ruff format .`
- `typecheck` — `uv run mypy .`
- `test` — `uv run pytest -q`
- `serve` — project-specific (see below)
- `build` — for `apps/*`, produces a Docker image via `docker buildx`.

Common JS project:
- `lint`, `format`, `typecheck` (`tsc --noEmit`), `test` (vitest), `build`,
  `serve`.

App-specific:
- `apps/web`: `serve` runs Vite dev server on port 5173.
- `apps/api`: `serve` runs uvicorn with reload.
- `apps/worker`: `serve` runs `celery -A worker.app worker -Q cpu,gpu` (the
  GPU container will override this to add `-Q gpu`).
- `apps/ingest-watcher`: `serve` runs the watcher loop.

Aggregate targets defined in `nx.json`:
- `nx run-many -t lint typecheck test` — CI gate.
- `nx affected -t lint test build` — used in PRs.

## Python project conventions

Each Python project's `pyproject.toml`:

- `requires-python = ">=3.12"`
- Tools configured at project level (NOT root) for ruff, mypy, pytest, so each
  project can opt into stricter rules independently.
- Dependencies on local libs declared as path deps:
  ```toml
  [tool.uv.sources]
  vd-db = { path = "../../libs/python/db", editable = true }
  vd-ml = { path = "../../libs/python/ml", editable = true }
  ```

## Linters / formatters

| Lang | Tool       | Notes                                                     |
|------|------------|-----------------------------------------------------------|
| Py   | ruff       | combined linter + formatter; replaces black + isort + flake8 |
| Py   | mypy       | strict in libs, regular in apps                           |
| TS   | eslint     | with @typescript-eslint                                   |
| TS   | prettier   | formatting                                                |
| TS   | tsc        | `--noEmit` for typecheck target                           |
| Both | pre-commit | runs ruff, prettier, eslint, mypy --strict on staged libs |

## Testing strategy (covered in detail in later plans)

- Python: pytest + pytest-asyncio. ML code that needs GPU is skipped by default
  via `pytest.mark.gpu`; CI runs them only on a GPU runner (or you run locally).
- DB tests use a transactional fixture against a real Postgres
  (testcontainers-python or a docker-compose `db-test` service).
- TS: vitest + React Testing Library for unit/component, Playwright for E2E
  against a docker-compose stack with seeded fixtures.

## Setup script

`tools/scripts/bootstrap.sh`:
1. Verify Node 20, pnpm, uv, docker, nvidia-container-toolkit are installed.
2. `pnpm install`.
3. `uv sync` for each Python project (driven by `@nxlv/python`'s `nx sync`).
4. `pre-commit install`.
5. `docker compose up -d postgres redis` to bring up data services.
6. `nx run api:migrate` to apply Alembic migrations.
7. Print readiness check.

## CI (optional in v1)

A simple GitHub Actions workflow (only if/when this lands in a repo):
- Job 1: `nx affected -t lint typecheck test build` against CPU-only image.
- Job 2 (manual or nightly): `nx run worker:test --gpu` against a self-hosted
  GPU runner.

## Open questions

- **`@nxlv/python` UV support**: the plugin's UV path is newer than the Poetry
  one. If we hit friction during setup, fallback is `nx:run-commands` per
  project wrapping `uv run …` — we lose the project graph but everything else
  keeps working. Decide at bootstrap time.
- **Single venv vs venv-per-project**: `@nxlv/python` defaults to per-project
  venvs. Keep it that way to keep dependency surfaces small (apps/api doesn't
  need torch).
