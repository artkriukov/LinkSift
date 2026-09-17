# Background processing worker

The worker separates Telegram ingestion from slow material processing. Ingestion creates a
`pending` processing attempt; one of any number of worker processes atomically claims it and
moves both the attempt and material to `processing`, then to `completed` or `failed`.

## Running it

Apply migrations with `make db-upgrade`, then run the bot and worker in separate terminals:

```console
make bot
make worker
```

The worker uses `LINKSIFT_DATABASE_URL`. Its poll interval, lease, heartbeat, processing timeout,
and maximum claim count are configured by the `LINKSIFT_WORKER_*` and
`LINKSIFT_PROCESSING_TIMEOUT_SECONDS` settings documented in `.env.example`.

## Claims, leases, and recovery

Claims use a single PostgreSQL transaction and `FOR UPDATE SKIP LOCKED`, ordered by attempt
creation time. This allows multiple workers without duplicate concurrent processing. A heartbeat
renews the lease during long work. After a crash, an expired `processing` attempt becomes
claimable again. Completion and failure are fenced by the current `worker_id` and unexpired lease,
so an obsolete worker cannot overwrite a newer result. Soft-deleted materials are never claimed.

Transient timeouts are returned to `pending` while `claim_count` is below the configured maximum.
Permanent errors, including `processor_not_configured`, fail immediately. No new material is
created for a retry.

## Shutdown

`SIGINT` and `SIGTERM` stop new claims. The active processor is allowed to finish within its own
configured timeout; its heartbeat then stops, processors are closed, and the database engine is
disposed. If the process is killed, lease expiry provides recovery.

## Adding a processor

Implement `MaterialProcessor.process(material) -> AnalysisResult` and register the instance for a
`source_type` in `ProcessorRouter` at composition time. Do not put provider SDK calls in the worker,
service, or repository. Production intentionally registers no fake result: unsupported types fail
with `processor_not_configured`. `ProcessingGuard` is the pre-provider extension point for user
blocks, material-size limits, daily quotas, and budget enforcement.

## Diagnosing stuck work

Inspect only operational columns in `processing_attempts`: `status`, `worker_id`, `heartbeat_at`,
`lease_expires_at`, and `claim_count`. A processing row whose lease is in the past is recoverable
and will be claimed on the next poll. Repeatedly increasing `claim_count` indicates a transient
failure. Avoid logging source text, full URLs, credentials, provider keys, or raw exceptions.
