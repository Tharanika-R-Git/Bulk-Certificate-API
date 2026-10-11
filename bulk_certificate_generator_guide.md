# Bulk Certificate Generator — Project Guide

## 1. Project Overview

The **Bulk Certificate Generator** is a backend application that accepts a list of recipients, generates a PDF certificate for each valid recipient using one predefined template, tracks the progress of a bulk job, and allows individual certificates to be downloaded.

The application must isolate failures: if generating one recipient's certificate fails, processing should continue for the remaining recipients.

### Core requirements

- Accept a bulk request containing recipient details and certificate information.
- Validate incoming data.
- Generate a PDF certificate for each recipient using a predefined template.
- Track job-level progress and recipient-level status.
- Continue processing when an individual recipient fails.
- Provide an API to check job status and download completed PDFs.
- Include automated tests and clear setup documentation.

---

## 2. Technology Stack

| Technology | Purpose |
|---|---|
| **Python** | Main programming language |
| **FastAPI** | REST API, request validation integration, and interactive API docs |
| **Pydantic** | Validate and describe request/response schemas |
| **PostgreSQL** | Persistent storage for jobs, recipients, statuses, and file metadata |
| **SQLAlchemy 2.x** | Python ORM and database access |
| **Alembic** | Version-controlled database schema migrations |
| **Celery** | Execute certificate-generation tasks in background workers |
| **Redis** | Broker that carries tasks from the API to Celery workers |
| **ReportLab** | Generate certificate PDF files |
| **Pytest** | Automated test framework |
| **HTTPX** | Test FastAPI endpoints |
| **Docker Compose** | Run local infrastructure such as PostgreSQL and Redis |
| **Local file storage** | Store generated PDFs for the assignment; object storage such as S3 can be added later |
| **Git** | Version control |

### Why this stack?

- **FastAPI** makes it straightforward to build typed REST endpoints and expose OpenAPI documentation.
- **PostgreSQL** persists job and recipient state so it survives API or worker restarts.
- **Celery + Redis** separates slow PDF generation from request handling and supports multiple workers.
- **ReportLab** generates PDFs programmatically without requiring a browser.
- **Pytest + HTTPX** make it possible to verify behavior automatically.
- **Docker Compose** gives the project a repeatable local setup.

> Keep the implementation no more complex than necessary. Kafka, Kubernetes, and multiple microservices are not required for this assignment.

---

## 3. High-Level Architecture

```text
Client
  |
  | POST /api/v1/certificate-jobs
  v
FastAPI API
  |                         \
  | save job + recipients    \ enqueue task IDs
  v                           v
PostgreSQL                  Redis broker
                               |
                               v
                         Celery workers
                               |
                               | generate PDFs
                               v
                       ReportLab + file storage
                               |
                               | update result/status
                               v
                           PostgreSQL

Client polls job status and downloads completed certificates through FastAPI.
```

### Component responsibilities

1. **FastAPI** receives requests, validates them, creates jobs, returns status, and serves downloads.
2. **PostgreSQL** is the source of truth for job and recipient state.
3. **Redis** carries queued tasks; it should not be the only place where job progress is stored.
4. **Celery workers** process recipient tasks independently.
5. **ReportLab** renders each certificate as a PDF.
6. **File storage** keeps the PDF bytes separate from relational metadata.

### Request lifecycle

1. A client submits a list of recipients and certificate details.
2. The API validates the request and rejects malformed batch-level input.
3. The API persists the job and its recipient records.
4. The API schedules work and responds with `202 Accepted` and a job ID.
5. Workers process recipient tasks independently.
6. Each worker generates a PDF, stores it, and updates the corresponding recipient status.
7. The job status is derived or updated from recipient outcomes.
8. The client polls the status endpoint and downloads successful certificates.

---

## 4. API Design

Base path: `/api/v1`

### 4.1 Create a certificate job

`POST /api/v1/certificate-jobs`

Example request:

```json
{
  "certificate": {
    "title": "Certificate of Completion",
    "course_name": "Backend Engineering",
    "issuer_name": "Example Academy",
    "issue_date": "2026-10-11"
  },
  "recipients": [
    {
      "name": "Asha Kumar",
      "email": "asha@example.com"
    },
    {
      "name": "Ravi Kumar",
      "email": "ravi@example.com"
    }
  ]
}
```

Expected behavior:

- Validate required fields and field lengths.
- Apply a documented maximum batch size.
- Decide and document whether a single invalid recipient rejects the whole request or is recorded as a recipient-level failure. A useful design is to reject malformed batch-level structure while recording independently invalid recipient entries as failed, provided the request schema can safely represent them.
- Persist the job and recipient records.
- Queue work only after the database records are committed.
- Return quickly rather than waiting for all PDFs to finish.

Example response (`202 Accepted`):

```json
{
  "job_id": "9fcb7d5a-9f6c-4c93-8b2d-4c51f5f9c1c2",
  "status": "queued",
  "total_recipients": 2,
  "status_url": "/api/v1/certificate-jobs/9fcb7d5a-9f6c-4c93-8b2d-4c51f5f9c1c2"
}
```

### 4.2 Get job status and progress

`GET /api/v1/certificate-jobs/{job_id}`

Example response:

```json
{
  "job_id": "9fcb7d5a-9f6c-4c93-8b2d-4c51f5f9c1c2",
  "status": "processing",
  "total": 100,
  "pending": 30,
  "processing": 10,
  "succeeded": 55,
  "failed": 5,
  "progress_percent": 60
}
```

In this example, progress is `(succeeded + failed) / total × 100`, so 60 of 100 recipients have reached a terminal state.

Recommended job states:

- `queued`
- `processing`
- `completed`
- `completed_with_errors`
- `failed`

Recommended recipient states:

- `pending`
- `processing`
- `succeeded`
- `failed`

Define the job as:
- `completed` when every recipient succeeds.
- `completed_with_errors` when all recipients reach a terminal state and at least one fails.
- `failed` for a job-level failure that prevents the job from being processed at all.

Do not mark a job complete merely because tasks were enqueued.

### 4.3 List recipient outcomes

`GET /api/v1/certificate-jobs/{job_id}/recipients`

Purpose:

- Show each recipient's status.
- Include failure information that is safe to expose.
- Support pagination, such as `?limit=50&offset=0`.
- Avoid returning stack traces, secrets, or internal filesystem paths.

### 4.4 Download an individual certificate

`GET /api/v1/certificate-jobs/{job_id}/certificates/{recipient_id}`

Expected behavior:

- Confirm the job and recipient exist and belong together.
- Confirm the recipient has succeeded and a PDF exists.
- Return the file as `application/pdf`.
- Return a meaningful `404` or `409` if the record does not exist or generation is not complete.
- If authentication is implemented, verify the caller is allowed to access the job and file.

### 4.5 Health check

`GET /health`

Return service health information. If the endpoint checks dependencies, clearly distinguish application health from database or queue availability.

---

## 5. Database Design

Use PostgreSQL for durable application state.

### 5.1 `certificate_jobs`

Suggested fields:

| Field | Purpose |
|---|---|
| `id` | UUID primary key |
| `status` | Job lifecycle state |
| `certificate_title` | Certificate title |
| `course_name` | Course or event name |
| `issuer_name` | Issuing organization |
| `issue_date` | Certificate issue date |
| `total_recipients` | Number of recipient records |
| `created_at` | Creation timestamp |
| `updated_at` | Last update timestamp |
| `completed_at` | Completion timestamp, nullable |

### 5.2 `certificate_recipients`

Suggested fields:

| Field | Purpose |
|---|---|
| `id` | UUID primary key |
| `job_id` | Foreign key to `certificate_jobs.id` |
| `name` | Recipient name |
| `email` | Recipient email |
| `status` | Recipient lifecycle state |
| `file_key` | Relative storage key for the generated PDF |
| `error_code` | Stable machine-readable failure code, nullable |
| `error_message` | Safe error summary, nullable |
| `attempt_count` | Number of processing attempts |
| `created_at` | Creation timestamp |
| `updated_at` | Last update timestamp |
| `completed_at` | Completion timestamp, nullable |

### Database guidelines

- Use UUIDs for job and recipient identifiers.
- Add indexes on `certificate_recipients.job_id` and status fields used for filtering.
- Add foreign-key constraints and appropriate non-null constraints.
- Use timezone-aware timestamps.
- Store file metadata or relative keys in PostgreSQL, not the PDF binary itself, unless there is a specific reason to use database blob storage.
- Never trust a client-supplied path when downloading a file.
- Use Alembic migrations rather than relying only on automatic table creation in production.
- Use database transactions for related job and recipient inserts.

---

## 6. PDF Generation

Use ReportLab to create a single, professional, predefined certificate layout.

### Suggested content

- Certificate title
- Recipient name
- Course or event name
- Issue date
- Issuer name
- Optional unique certificate ID

### Requirements

- Validate and safely render recipient data.
- Handle long names and text without clipping.
- Generate a valid PDF for each successful recipient.
- Store files under a deterministic path, for example:

```text
storage/
  jobs/
    <job_id>/
      certificates/
        <recipient_id>.pdf
```

- Keep storage paths relative to a configured storage root.
- Do not allow user input to choose arbitrary filesystem paths.
- Return downloads through the API rather than exposing the storage directory directly.
- Ensure a failed PDF write does not result in a recipient being marked successful.

A deterministic file key helps make repeated processing of the same recipient idempotent.

---

## 7. Background Processing and Failure Isolation

### Why use background tasks?

PDF generation can be slow. If the API generated every certificate inside the original HTTP request, the request could time out and consume API worker capacity. A queue lets the API accept work quickly while workers process it separately.

### Recommended flow

1. Persist the job and recipient records in PostgreSQL.
2. Commit the transaction.
3. Enqueue a task containing stable identifiers, such as `job_id` and `recipient_id`, rather than copying the full request payload.
4. The Celery worker loads the recipient and job data.
5. The worker claims or transitions the recipient to `processing` safely.
6. The worker generates and stores the PDF.
7. The worker records `succeeded` or `failed` and updates timestamps.
8. The job's overall status is recalculated from recipient states.

### Failure isolation

Process each recipient as an independent task. A failure for one recipient must not terminate the whole batch.

For each task:

- Catch and record expected recipient-level errors.
- Log unexpected exceptions with enough context to diagnose the issue.
- Avoid exposing stack traces to API clients.
- Retry only errors that are likely transient, such as temporary infrastructure failures.
- Use bounded retries and exponential backoff for transient failures.
- Do not endlessly retry invalid recipient data or deterministic programming errors.
- Continue processing other recipients even if one task fails.

### Idempotency and duplicate delivery

Distributed queues can deliver a task more than once. A worker may also crash after writing a file but before updating the database.

Design for **at-least-once task delivery** rather than claiming exactly-once execution:

- Use stable job and recipient IDs.
- Use a deterministic file key.
- Make repeated generation safe.
- Make state updates conditional or transactional where needed.
- Ensure a duplicate task does not corrupt the job counters or create conflicting records.

### Stuck tasks and recovery

Document how tasks left in `processing` after a worker crash can be detected and recovered. A recovery process may identify records that have remained in `processing` beyond a configured timeout and safely return them to `pending` or retry them.

### Queue/database consistency

There is a gap between committing a database transaction and publishing a task to Redis. For a small assignment, document this risk and implement a reasonable recovery mechanism. A **transactional outbox** is a stronger option: record intended task publication in PostgreSQL within the same transaction, then have a dispatcher publish it to Redis and mark it delivered. Implement it only if time allows and you can explain it.

---

## 8. Testing Requirements

Use Pytest and HTTPX for automated tests.

### Required tests

1. **Create job:** A valid request creates a job and recipient records.
2. **Input validation:** Missing fields, invalid dates/emails, empty batches, and batches over the limit are handled correctly.
3. **PDF generation:** A generated file exists and can be opened as a valid PDF.
4. **Status/progress:** Job and recipient status, counts, and progress are accurate.
5. **Individual failure:** One failed recipient does not prevent other recipients from succeeding.
6. **Download:** A successful certificate can be downloaded with the correct PDF content type.
7. **Unavailable download:** A missing or unfinished certificate returns an appropriate error.
8. **Pagination:** Recipient listing handles limits and offsets correctly.
9. **Duplicate task:** Reprocessing a recipient does not corrupt state or produce duplicate database records.
10. **Persistence:** Job state remains available after the API process is restarted.

### Testing strategy

- Unit-test PDF generation and state-transition logic independently.
- Use a test database for database/API integration tests.
- Mock or replace the task queue in ordinary API tests so they do not require a live Redis service.
- Keep infrastructure-dependent tests separate and label them as integration tests.
- Test worker behavior directly for success, permanent failure, transient failure, and retry handling.
- Run the tests and fix failures before claiming that the project passes.

---

## 9. Suggested Project Structure

```text
bulk-certificate-generator/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── v1/
│   │       ├── jobs.py
│   │       ├── recipients.py
│   │       └── health.py
│   ├── core/
│   │   ├── config.py
│   │   └── logging.py
│   ├── db/
│   │   ├── session.py
│   │   └── base.py
│   ├── models/
│   │   ├── job.py
│   │   └── recipient.py
│   ├── schemas/
│   │   ├── job.py
│   │   └── recipient.py
│   ├── repositories/
│   ├── services/
│   │   ├── certificate_service.py
│   │   └── pdf_service.py
│   └── workers/
│       ├── celery_app.py
│       └── tasks.py
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── storage/
├── .env.example
├── .gitignore
├── alembic.ini
├── Dockerfile
├── compose.yaml
├── requirements.txt
└── README.md
```

This is a suggested layout, not a requirement to create empty files. Keep modules that contain real functionality; avoid unnecessary abstractions.

---

## 10. Local Setup and Running

Exact commands depend on the files Claude Code generates. The following is a typical Windows PowerShell workflow.

### Prerequisites

- Python version supported by the chosen dependencies
- Git
- Docker Desktop running with the Linux container engine
- Claude Code, if you are using it to build the project

### Start infrastructure

From the project directory, if Claude creates a valid Compose file:

```powershell
docker compose up -d postgres redis
docker compose ps
```

The actual service names must match those in `compose.yaml`.

### Create and activate a virtual environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, use the Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Configure environment variables

Create a local `.env` file based on `.env.example`. Configure the database URL, Redis URL, storage directory, and other required settings.

Do not commit `.env` or real credentials to Git.

### Run migrations

Use the migration command documented by the project, commonly:

```powershell
alembic upgrade head
```

### Start the API

```powershell
uvicorn app.main:app --reload
```

### Start a Celery worker

Open a **second PowerShell terminal**, activate the same environment, and run the worker command documented by the project. A typical Windows development command is:

```powershell
celery -A app.workers.celery_app:celery_app worker --loglevel=info --pool=solo
```

The Celery application variable and module path must match the actual code. `--pool=solo` can help with local Windows development; use an appropriate supported worker pool in production, typically on Linux.

### Open the API documentation

When the server is running, visit:

- Swagger UI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### Run tests

```powershell
python -m pytest -q
```

Use the README and actual generated configuration as the source of truth if any command differs.

---

