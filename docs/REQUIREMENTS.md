# ModelHarbor: requirements and acceptance

## Product goal

A small LLM gateway with explicit budgets, fallback and accountable usage. A reviewer should be able to install the package, run its tests, inspect its SQL boundaries and exercise the core workflow without a custom frontend.

## Functional requirements

- Groq and OpenAI adapters behind the auto model alias
- Hashed client tokens, per-client token buckets and durable token budgets
- Provider fallback, a process-local circuit breaker and exact TTL caching
- Basic input masking, prompt guardrails, idempotency and usage reports

## Acceptance conditions

1. Client budgets and cached responses cannot cross client boundaries.
2. A request key cannot be reused with another payload.
3. Admission cannot oversubscribe a budget under concurrent requests.
4. An uncertain provider outcome must not be reported as a verified zero-cost failure.

## Quality requirements

Persist domain state transactionally; validate untrusted inputs; keep provider failures visible; avoid credential and prompt disclosure in diagnostic errors; provide an installable Python package, authenticated API, container and repeatable automated checks. Keep fixture evidence distinct from public-data and live-provider evidence.

## Scope boundary

stream=true returns buffered SSE after completion, not native upstream streaming. Caching is exact, not semantic. The circuit breaker is process-local. Token reservation is a conservative estimate, not a guaranteed dollar spending cap; unknown upstream outcomes retain a reservation. Cost is unknown unless operator-supplied rates are configured. Regex masking and prompt rules are limited safeguards.

## Evaluation plan

Budget contention, cache isolation and expiry, token-bucket limits, fallback, circuit recovery, provider contract errors and uncertain usage accounting. External checks need the credentials, model files or network access described in the runbook. Before publishing quality claims, create a labelled evaluation set and report sample size, metric definition, model version and measured failures. Use an atomic shared rate limiter before multiple replicas; add native provider streaming and measured tokenizer estimates before advertising those features.
