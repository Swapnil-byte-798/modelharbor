# ModelHarbor

A small LLM gateway with explicit budgets, fallback and accountable usage.

[![Python verification](https://github.com/Swapnil-byte-798/modelharbor/actions/workflows/ci.yml/badge.svg)](https://github.com/Swapnil-byte-798/modelharbor/actions/workflows/ci.yml)

Project 6 in a Python and SQL AI engineering portfolio. The interface is a Python CLI and FastAPI's generated API documentation.

## What works

- Groq and OpenAI adapters behind the auto model alias
- Hashed client tokens, per-client token buckets and durable token budgets
- Provider fallback, a process-local circuit breaker and exact TTL caching
- Basic input masking, prompt guardrails, idempotency and usage reports

## Run it

Python 3.11 or 3.12. SQLite is included with Python.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m modelharbor demo
python -m modelharbor setup
python -m modelharbor serve --port 8020
```

Open http://127.0.0.1:8020/docs. `setup` prompts for credentials without displaying them, generates independent operator/reviewer tokens, and stores them in an ignored file with owner-only permissions. Use the operator token as `Authorization: Bearer ...`; account, client and tenant endpoints issue their own scoped tokens. Do not commit any of these values.

The demo is explicitly labelled: authored fixtures exercise the workflow, not a live provider. `check-keys` reports configuration only and never claims a provider has been validated.

## Credentials

GROQ_API_KEY and OPENAI_API_KEY. One configured provider can serve requests; both are needed to verify real fallback.

To reuse a provider key across these repositories, run `python -m modelharbor setup --shared` before the local `setup` command. The shared prompt adds missing keys and preserves existing nonempty keys. Local environment variables take precedence. See [.env.example](.env.example) for names only; real keys are never shipped.

## Design and boundaries

Client token → admission and quota reservation → exact cache → provider/circuit → usage reconciliation → OpenAI-style response

stream=true returns buffered SSE after completion, not native upstream streaming. Caching is exact, not semantic. The circuit breaker is process-local. Token reservation is a conservative estimate, not a guaranteed dollar spending cap; unknown upstream outcomes retain a reservation. Cost is unknown unless operator-supplied rates are configured. Regex masking and prompt rules are limited safeguards.

## Verification

Budget contention, cache isolation and expiry, token-bucket limits, fallback, circuit recovery, provider contract errors and uncertain usage accounting. Common tests also cover hidden setup, configuration precedence, provider response validation, API authentication and transactional rollback.

[Verification record](evidence/verification.json) separates automated checks from provider-dependent acceptance. No result represents all possible inputs, production load, or a calibrated model-quality benchmark.

## Read further

- [Requirements and acceptance](docs/REQUIREMENTS.md)
- [Architecture and decisions](docs/ARCHITECTURE.md)
- [Runbook and key setup](docs/RUNBOOK.md)
- [Study guide](docs/STUDY_GUIDE.md)

## Next engineering milestone

Use an atomic shared rate limiter before multiple replicas; add native provider streaming and measured tokenizer estimates before advertising those features.
