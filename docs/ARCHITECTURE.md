# ModelHarbor: architecture

## Request and data path

Client token → admission and quota reservation → exact cache → provider/circuit → usage reconciliation → OpenAI-style response

`api.py` validates transport input and credentials. `service.py` owns domain invariants and SQL transitions. `runtime.py` supplies small, vendored transport/configuration conventions so the repository can install independently. `cli.py` exposes setup, a labelled demo and serving commands. SQL schemas live beside the service that owns them.

## Decisions

Python and SQL keep the project aligned with the portfolio's existing skills. FastAPI supplies an inspectable contract without authored web code. SQLite provides a durable, low-cost local path; it is not a distributed database. The service owns transaction boundaries rather than spreading writes across API handlers. Domain services accept provider fixtures for tests; production commands never replace failed upstream calls with fixtures.

Provider keys come from owner-only files or the process environment. Tokens are distinct from provider keys. Never put a provider key into a public API client's configuration. Concurrent SQL writes are admitted transactionally; processes that die during external work can require operator recovery rather than unsafe automatic replay.

## Failure boundaries

1. Client budgets and cached responses cannot cross client boundaries.
2. A request key cannot be reused with another payload.
3. Admission cannot oversubscribe a budget under concurrent requests.
4. An uncertain provider outcome must not be reported as a verified zero-cost failure.

Missing credentials return a configuration failure. Invalid provider structures fail validation. Network requests have timeouts and no silent retries through the common JSON client. An upstream timeout can still consume provider tokens; local rollback cannot undo external billing.

## Capacity and security limits

stream=true returns buffered SSE after completion, not native upstream streaming. Caching is exact, not semantic. The circuit breaker is process-local. Token reservation is a conservative estimate, not a guaranteed dollar spending cap; unknown upstream outcomes retain a reservation. Cost is unknown unless operator-supplied rates are configured. Regex masking and prompt rules are limited safeguards.

Bind locally for development. Before external hosting, add TLS, gateway request-size limits, restricted egress, protected persistent storage, retention policies and a process-specific secret store. No internet-facing deployment or production security certification is claimed by this repository.
