# Bulk Certificate Generator API

A production-quality backend that accepts **one bulk request** containing many
recipients, validates them, generates personalized PDF certificates
asynchronously, tracks per-recipient and per-job progress, and serves the
finished certificates for download.

A failure for one recipient never prevents the others from being processed.

---

## 1. Architecture

```
Client ──HTTP──▶ FastAPI ──▶ PostgreSQL (jobs, recipients, outbox)
                   │                 ▲
                   │ enqueue         │ state (source of truth)
                   ▼                 │
                 Redis ──▶ Celery workers ──▶ ReportLab ──▶ file storage
```

```mermaid
flowchart LR
    C[Client] -->|POST job| API[FastAPI]
    API -->|persist job + recipients + outbox<br/>in one transaction| PG[(PostgreSQL)]
    API -->|202 Accepted + status URL| C
    API -.->|enqueue after commit| R[(Redis broker)]
    OB[Outbox dispatcher<br/>Celery beat] -->|publish unpublished| R
    R --> W[Celery workers]
    W -->|claim + render| PDF[ReportLab]
    PDF --> S[(File storage)]
    W -->|update status / counters| PG
    REAP[Stale reaper<br/>Celery beat] -->|recover crashed work| PG
    C -->|GET status / recipients| API
    C -->|GET certificate| API --> S
```

**Responsibilities**

| Component | Responsibility |
|-----------|----------------|
| FastAPI | Request validation, job creation, status/recipient queries, downloads |
| PostgreSQL | Durable source of truth: jobs, recipients, statuses, retry counts, file keys, outbox |
| Redis | Transient transport for background task messages (the broker) |
| Celery workers | Process each recipient independently and idempotently |
| ReportLab | Render the fixed landscape certificate template |
| Storage | Pluggable `Storage` interface; `LocalStorage` writes to the filesystem |

The API **never** generates a batch synchronously inside the HTTP request — it
persists everything and returns `202 Accepted`, then workers do the rendering.

---

## 2. Prerequisites

- Python 3.12+ (developed and tested on 3.13)
- Docker Desktop (for local PostgreSQL + Redis)
- Windows PowerShell (commands below) — equivalents work on macOS/Linux

---

## 3. Setup (Windows PowerShell)

```powershell
# From the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Create your local environment file
Copy-Item .env.example .env
```

### Environment variables

All configuration is read from the environment / `.env` (see `.env.example`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+psycopg://certs:certs@localhost:5432/certs` | SQLAlchemy DB URL |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Redis broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery result backend |
| `MAX_BATCH_SIZE` | `1000` | Max recipients per request (job-level validation) |
| `STORAGE_LOCAL_DIR` | `storage` | Directory for generated PDFs |
| `RECIPIENT_LOCK_TIMEOUT_SECONDS` | `300` | When a `PROCESSING` recipient is considered abandoned |
| `MAX_RETRIES` | `3` | Automatic retries for transient failures |
| `RETRY_BACKOFF_BASE_SECONDS` | `5` | Base for exponential backoff (`base * 2**attempt`) |

Never commit a real `.env`; it is git-ignored.

### Start PostgreSQL and Redis

```powershell
docker compose up -d
```

### Apply database migrations

```powershell
alembic upgrade head
```

### Start the API

```powershell
uvicorn app.main:app --reload
```

Interactive docs: http://localhost:8000/docs

### Start Celery workers and the beat scheduler

Open two more terminals (with the venv activated). On Windows use the `solo`
pool (`-P solo`); prefork is not supported on Windows:

```powershell
# Worker
celery -A app.workers.celery_app:celery_app worker --loglevel=info -Q certificates -P solo

# Beat (runs the outbox dispatcher + stale-recipient reaper)
celery -A app.workers.celery_app:celery_app beat --loglevel=info
```

On macOS/Linux you can drop `-P solo` to use the default prefork pool.

---

## 4. Running the tests

The suite is fully offline — it uses an isolated SQLite database and a temp
storage directory, and requires **no** Redis or PostgreSQL:

```powershell
pytest
```

Integration tests that need live services (none required for grading) would be
marked `@pytest.mark.integration` and are deselected by default.

---

## 5. API reference and example flow

Base path: `/api/v1`

### 5.1 Create a job — `POST /api/v1/certificate-jobs`

```powershell
curl -X POST http://localhost:8000/api/v1/certificate-jobs `
  -H "Content-Type: application/json" `
  -d '{
        "event_name": "Advanced Python Workshop",
        "issuer_name": "Acme Academy",
        "issue_date": "2026-10-11",
        "recipients": [
          {"name": "Ada Lovelace", "email": "ada@example.com", "certificate_number": "CERT-001"},
          {"name": "Alan Turing",  "email": "alan@example.com", "certificate_number": "CERT-002"},
          {"name": "",             "email": "not-an-email",     "certificate_number": ""}
        ]
      }'
```

Response `202 Accepted`:

```json
{
  "job_id": "6f1b2c3d-....",
  "status": "QUEUED",
  "status_url": "/api/v1/certificate-jobs/6f1b2c3d-....",
  "total_recipients": 3,
  "accepted": 2,
  "rejected": 1
}
```

The third recipient failed recipient-level validation (empty name, bad email,
missing certificate number) and is recorded as a `FAILED` recipient — the valid
two are still processed.

### 5.2 Check job progress — `GET /api/v1/certificate-jobs/{job_id}`

```json
{
  "job_id": "6f1b2c3d-....",
  "event_name": "Advanced Python Workshop",
  "issuer_name": "Acme Academy",
  "issue_date": "2026-10-11",
  "status": "COMPLETED_WITH_ERRORS",
  "total": 3,
  "processed": 3,
  "success_count": 2,
  "failure_count": 1,
  "progress_percentage": 100.0,
  "created_at": "2026-10-11T10:00:00+00:00",
  "completed_at": "2026-10-11T10:00:04+00:00"
}
```

`progress_percentage = (success + failure) / total * 100` — i.e. terminal
recipients over total.

### 5.3 List recipient results — `GET /api/v1/certificate-jobs/{job_id}/recipients?page=1&page_size=50`

```json
{
  "items": [
    {
      "recipient_id": "a1...",
      "name": "Ada Lovelace",
      "email": "ada@example.com",
      "certificate_number": "CERT-001",
      "status": "SUCCESS",
      "error_message": null,
      "download_url": "/api/v1/certificate-jobs/6f1b2c3d-.../certificates/a1..."
    },
    {
      "recipient_id": "c3...",
      "name": "",
      "email": "",
      "certificate_number": "",
      "status": "FAILED",
      "error_message": "name is required; email format is invalid; certificate number is required",
      "download_url": null
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 50
}
```

### 5.4 Download a certificate — `GET /api/v1/certificate-jobs/{job_id}/certificates/{recipient_id}`

```powershell
curl -L -o certificate.pdf `
  http://localhost:8000/api/v1/certificate-jobs/6f1b2c3d-.../certificates/a1...
```

- `200` with `application/pdf` when the recipient belongs to the job **and**
  succeeded.
- `404` if the recipient doesn't exist or belongs to a different job.
- `409` if the recipient exists but hasn't succeeded (pending/processing/failed).

### 5.5 Health — `GET /health`

```json
{ "status": "ok", "database": "up", "broker": "up" }
```

`status` is liveness (we responded); `database` and `broker` are readiness
probes.

---

## 6. Data model

**CertificateJob**: `id` (UUID PK), `event_name`, `issuer_name`, `issue_date`,
`status`, denormalized `total_count` / `success_count` / `failure_count`,
`created_at`, `completed_at`.

**CertificateRecipient**: `id` (UUID PK), `job_id` (FK), `name`, `email`,
`certificate_number`, `status`, `file_key`, `error_message` (safe), `retry_count`,
`locked_at`, `created_at`, `updated_at`.

**OutboxEntry**: `id`, `job_id`, `recipient_id`, `published`, timestamps.

**Certificate-number uniqueness scope.** Enforced **per job** via a partial
unique index on `(job_id, certificate_number)` that excludes `FAILED` rows. The
same external number may be reused across unrelated jobs, but must be unique
within one batch so results are unambiguous. Validation-rejected duplicates are
all written as `FAILED` display rows, and the partial index keeps those from
colliding with each other.

Recipient rows are the **source of truth**. Job counters are a denormalized
cache, only ever mutated with atomic `col = col + 1` SQL and reconciled from the
recipient rows at finalization under a row lock.

---

## 7. State transitions

**Recipient:** `PENDING → PROCESSING → SUCCESS` (terminal), or
`PROCESSING → FAILED` (terminal) on permanent failure / exhausted retries. A
transient failure resets `PROCESSING → PENDING` and bumps `retry_count` up to
`MAX_RETRIES`. Validation-rejected recipients are written directly as `FAILED`.

**Job:** `QUEUED → PROCESSING` when the first recipient is claimed; then, once
**all** recipients are terminal:

- `COMPLETED` — every recipient succeeded.
- `COMPLETED_WITH_ERRORS` — at least one success and at least one failure.
- `FAILED` — zero successes.

A job with one failed recipient still completes once the rest finish.

---

## 8. Failure handling & reliability

- **Partial failure isolation:** each recipient is a separate task; one failing
  recipient never aborts the batch.
- **Transient vs permanent:** transient errors (I/O, unexpected exceptions)
  retry with bounded exponential backoff (`base * 2**attempt`); permanent errors
  (`PermanentError`) are not retried.
- **Idempotency:** a task claims its recipient with a conditional
  `UPDATE ... WHERE status = PENDING (or stale PROCESSING)`. Terminal recipients
  are skipped, so duplicate deliveries are safe.
- **Crash recovery:** `task_acks_late=True` + `task_reject_on_worker_lost=True`
  redeliver a task if the worker dies mid-render. The claim reclaims a stale
  lock; a periodic reaper resets recipients abandoned past
  `RECIPIENT_LOCK_TIMEOUT_SECONDS`, so jobs never hang.
- **Transactional outbox:** job + recipients + one outbox row per valid
  recipient are committed in a single transaction. Enqueuing happens after
  commit; if the broker is down the failure is swallowed and the periodic
  `dispatch_outbox` task publishes the unpublished rows later. A valid recipient
  is therefore never stranded.
- **Redis durability (honest statement):** Redis is an in-memory broker. With
  default persistence a broker crash can lose in-flight messages. The outbox
  (publishes anything not yet acknowledged as published) and the stale reaper
  (recovers claimed-but-unfinished work) together make the **database** the
  durable authority; Redis is treated as best-effort transport. Delivery is
  therefore *at-least-once*, which is why every task is idempotent.

---

## 9. Design decisions & trade-offs

- **Celery + Redis** over a hand-rolled queue: mature retry/ack/beat semantics
  with minimal code. Redis is simple to run; the outbox compensates for its weak
  delivery guarantees.
- **Outbox** over "just enqueue in the request": a naive enqueue after commit
  can lose recipients if the broker is briefly unavailable. The outbox makes
  recovery automatic and is simple to reason about.
- **Partial unique index** over global uniqueness or no constraint: expresses
  the real rule (unique active certificate per job) without rejecting the
  display rows we keep for rejected duplicates.
- **Processing core decoupled from Celery** (`app/services/processing.py`):
  the business logic is unit-tested directly with a real DB session and mocked
  PDF/storage, so tests need no broker.
- **Denormalized counters + recipient source of truth:** fast status reads
  without risking drift, because finalization reconciles under a row lock.

---

## 10. Current limitations & production improvements

- **Local filesystem storage** only (behind the `Storage` interface). For
  production, add an `S3Storage` implementation and stream downloads /
  return pre-signed URLs instead of proxying bytes.
- **Downloads proxy bytes through the API.** Fine for the assignment; large
  scale should offload to object storage + CDN.
- **No authentication/authorization.** These endpoints are unauthenticated —
  add API keys/OAuth and per-tenant scoping before any real deployment.
- **Outbox dispatch is poll-based** (every 10s). Acceptable here; a higher-scale
  system might use `LISTEN/NOTIFY` or a dedicated relay for lower latency.
- **No rate limiting / request-size cap** beyond `MAX_BATCH_SIZE`.
- **Single template.** Multiple templates / branding would need a template
  registry and validated inputs.

See `INTERVIEW_GUIDE.md` for the deeper "why" behind each of these.

