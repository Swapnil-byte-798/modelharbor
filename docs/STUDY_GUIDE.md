# ModelHarbor: study guide

## Explain the problem

A small LLM gateway with explicit budgets, fallback and accountable usage. Explain who uses the workflow and why each confirmation, isolation or validation boundary exists before describing libraries.

## Read the implementation

1. Read `service.py` and its SQL schema. Name the durable entities and draw their valid state transitions.
2. Trace one successful API request from its Pydantic input to its committed writes.
3. Trace a provider failure and identify what can and cannot be rolled back.
4. Read the tests that enforce the acceptance conditions below. Explain why each failure would matter to a user.

1. Client budgets and cached responses cannot cross client boundaries.
2. A request key cannot be reused with another payload.
3. Admission cannot oversubscribe a budget under concurrent requests.
4. An uncertain provider outcome must not be reported as a verified zero-cost failure.

## Interview discussion

- Where is the transaction boundary, and what happens if the process dies immediately after it?
- How are retries bound to the original request? Which operation can safely repeat?
- Which inputs are untrusted, and how are externally generated fields validated?
- What is tested with fixtures, what was measured on public data, and what remains unmeasured?
- What would change with ten times the data, multiple workers, or another tenant?

## Honest project explanation

Describe the implemented behavior, then demonstrate a representative test and explain its failure condition. Do not present mock latency, authored examples, uncalibrated scores or optional integrations as measured production results.

Known boundaries: stream=true returns buffered SSE after completion, not native upstream streaming. Caching is exact, not semantic. The circuit breaker is process-local. Token reservation is a conservative estimate, not a guaranteed dollar spending cap; unknown upstream outcomes retain a reservation. Cost is unknown unless operator-supplied rates are configured. Regex masking and prompt rules are limited safeguards.

## Practical extension

Use an atomic shared rate limiter before multiple replicas; add native provider streaming and measured tokenizer estimates before advertising those features. Define a measurable acceptance criterion before extending the implementation.
