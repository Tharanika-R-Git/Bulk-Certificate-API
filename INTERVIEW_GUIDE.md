# Interview Guide — Bulk Certificate Generator

This guide explains the system using **this** implementation, with file
references, so you can defend each decision.

---

## 1. Why is a queue needed?

Rendering a PDF with ReportLab is CPU/IO work measured in tens-to-hundreds of
milliseconds. A single request of 10,000 recipients rendered synchronously would
hold the HTTP connection open for minutes, risk timeouts, and tie up a web
worker. Instead, `POST /api/v1/certificate-jobs`
([app/api/jobs.py](app/api/jobs.py)) only **validates and persists**, then
returns `202 Accepted`. The actual rendering is pushed to background workers via
a queue. This keeps the API fast and lets rendering scale horizontally
(add workers) independently of the web tier.

## 2. Why Celery and Redis specifically?

- **Celery** gives us retries with backoff, late acknowledgement, worker-loss
  rejection, and a beat scheduler for periodic jobs — all configured in
  [app/workers/celery_app.py](app/workers/celery_app.py) — without writing a
  queue runtime ourselves.
- **Redis** is a lightweight, easy-to-run broker. Its weakness (in-memory, weak
  delivery guarantees) is deliberately compensated by the DB-backed outbox and
  reaper, so we get Redis's simplicity without betting correctness on it.

For a brand-new large system you might choose a log-based broker; for this scope
Celery+Redis is the pragmatic, low-infrastructure choice the assignment asked
for.

## 3. Why do PostgreSQL and Redis have different responsibilities?

- **PostgreSQL = durable source of truth.** Every job, recipient, status, retry
  count, file key and outbox row lives here
  ([app/db/models.py](app/db/models.py)). It survives restarts and crashes.
- **Redis = transient transport.** It only carries "please process recipient X
  of job Y" messages. If Redis lost everything, no *result* would be lost —
  the outbox would re-publish and workers would reprocess from DB state.

Keeping durable state out of Redis is what lets us treat delivery as
best-effort/at-least-once.

## 4. How do job and recipient state transitions work?

See [app/db/enums.py](app/db/enums.py) for the documented state machine and
[app/services/processing.py](app/services/processing.py) /
[app/services/finalization.py](app/services/finalization.py) for enforcement.

- A recipient starts `PENDING` (valid) or `FAILED` (rejected at validation).
- A worker moves it `PENDING → PROCESSING` by an atomic conditional UPDATE
  (`recipients_repo.claim`), renders, then sets `SUCCESS` or `FAILED`.
- The job starts `QUEUED`, flips to `PROCESSING` on first claim
  (`mark_processing_if_queued`), and is finalized to `COMPLETED` /
  `COMPLETED_WITH_ERRORS` / `FAILED` only when **no** recipient is still
  `PENDING`/`PROCESSING`.

## 5. How is progress calculated under concurrency?

`progress_percentage = (success_count + failure_count) / total_count * 100`
([app/api/deps.py](app/api/deps.py) `progress_percentage`). The counters are
updated with atomic SQL increments (`success_count = success_count + 1`) so two
workers finishing simultaneously can't lose an update. At finalization
(`maybe_finalize_job`) we **re-derive** the counts from the recipient rows under
a `SELECT ... FOR UPDATE` lock on the job and write the authoritative values,
eliminating any drift. The recipient rows — not the counter — are the source of
truth.

## 6. How do retries and idempotency work?

- **Retries:** `process_recipient` classifies failures. A `PermanentError` → no
  retry. Any other exception → transient: if `retry_count < MAX_RETRIES`, the
  recipient is reset to `PENDING`, `retry_count` is bumped, and the task returns
  `Outcome.RETRY`. The Celery wrapper
  ([app/workers/tasks.py](app/workers/tasks.py)) raises `self.retry` with
  `countdown = base * 2**attempt` (exponential backoff). Once the budget is
  exhausted the recipient becomes `FAILED`.
- **Idempotency:** the claim UPDATE only succeeds from `PENDING` (or a *stale*
  `PROCESSING`). A duplicate delivery of an already-`SUCCESS`/`FAILED` recipient
  hits the terminal-state guard and returns `Outcome.SKIPPED`. Re-running a task
  therefore never double-renders or double-counts (covered by
  `test_processing_is_idempotent`).

## 7. What happens when a worker crashes?

Two layers:

1. `task_acks_late=True` + `task_reject_on_worker_lost=True` mean the broker
   redelivers the task; the redelivered task reclaims the recipient because its
   `PROCESSING` lock is now stale (`locked_at` older than
   `RECIPIENT_LOCK_TIMEOUT_SECONDS`).
2. If no redelivery happens (e.g. the message was lost), the periodic
   `reap_stale_recipients` task
   ([app/workers/tasks.py](app/workers/tasks.py)) resets stale `PROCESSING`
   recipients back to `PENDING` and re-enqueues them.

So a crash mid-render results in reprocessing, never a stuck job.

## 8. What happens when Redis is unavailable?

- **At request time:** `publish_pending`
  ([app/services/dispatch.py](app/services/dispatch.py)) swallows the enqueue
  error; the outbox rows stay `published = false`. The request still returns
  `202` because the data is already committed.
- **Recovery:** when Redis is back, the beat-scheduled `dispatch_outbox` task
  publishes the unpublished rows and marks them published.
- **Workers:** can't receive work while Redis is down, but no state is lost;
  processing resumes from DB state once Redis returns.

## 9. How does the transactional outbox work?

In `job_service.create_job` ([app/services/job_service.py](app/services/job_service.py)),
the job, all recipient rows, and one `OutboxEntry` per **valid** recipient are
written inside a single transaction and committed together. Because the outbox
row and the recipient are committed atomically, there is no window where a
recipient exists but its "please enqueue me" intent is lost. Publication is then
a separate concern: inline best-effort now, periodic `dispatch_outbox` as the
guaranteed catch-up. `fetch_unpublished` uses
`FOR UPDATE SKIP LOCKED` so multiple dispatchers don't double-handle rows.

**Guarantee:** at-least-once enqueue of every valid recipient. **Limitation:**
not exactly-once — hence idempotent tasks. Dispatch latency is bounded by the
beat interval (10s) in the worst case.

## 10. How does it scale to 100,000 recipients?

- The request stays cheap: it's one bulk insert of recipients + outbox rows and
  a `202`. (At 100k you'd batch the inserts and likely raise `MAX_BATCH_SIZE` or
  accept an uploaded file.)
- Throughput scales by adding Celery workers/machines — each recipient is an
  independent, idempotent unit.
- Status reads stay O(1) thanks to the denormalized counters; recipient listing
  is indexed by `job_id` and paginated.

## 11. What bottlenecks appear first?

1. **PDF rendering CPU** — the dominant cost; mitigated by more workers.
2. **Per-recipient DB round-trips** (claim → success → finalize). At high
   volume, batch the status writes and finalize less often (e.g. only when the
   job's non-terminal count hits zero, which we already check).
3. **Download throughput** proxied through the API — move to object storage +
   pre-signed URLs.
4. **Outbox table growth / dispatch polling** — add partial index on
   `published = false` (present) and prune published rows.

## 12. What could be simplified for a small deployment?

- Drop the outbox and enqueue inline, accepting that a broker outage could
  strand recipients until a manual re-run — fine if you also keep the reaper or
  a "re-enqueue pending" admin task.
- Use SQLite instead of PostgreSQL (the code already runs on it for tests),
  trading concurrency for zero infrastructure.
- Run a single `-P solo` worker and no beat if periodic recovery isn't needed.
- Collapse the repositories/services split if the team prefers fewer layers.

The architecture is intentionally layered so these simplifications are
subtractive, not rewrites.
