# Revenium MLflow SDK

## What This Is

`revenium-mlflow` (import package `revenium_mlflow`, product name "Revenium MLflow SDK") is a
Revenium-supported Python SDK that lets an MLflow-instrumented application send economic telemetry
to Revenium without forking or modifying MLflow. It keeps MLflow as the engineering system of record
for traces, evaluation, and experiments, and adds the attribution, tool metering, and job-outcome
signals Revenium needs to be the authoritative rating source.

It is built for teams already running MLflow tracing against an MLflow Tracking Server who want
Revenium cost attribution, controls, and job ROI on the same traces. It is a Revenium product and is
neither part of, nor endorsed by, the MLflow project.

## Core Value

An MLflow-instrumented application keeps every trace in its Tracking Server *and* reaches Revenium
with correct, attributable economic telemetry — without changing MLflow and without double-counting
a single model call, tool execution, or job outcome.

## Business Context

- **Customer**: Revenium customers running MLflow tracing who need per-customer/per-job AI cost attribution
- **Revenue model**: Drives Revenium metering volume; the SDK is distribution, not a separate SKU
- **Success metric**: MLflow-sourced spans ingested and correctly attributed in Revenium, with zero duplicate completion or tool records
- **Strategy notes**: Sibling integration SDKs — `revenium-python-sdk` (canonical middleware), `revenium-litellm-guardrail` (per-integration repo precedent)

## Requirements

### Validated

(None yet — greenfield repository, ship to validate)

### Active

- [ ] Installable `revenium-mlflow` distribution (wheel + sdist + editable) following sibling packaging conventions
- [ ] Explicit typed public API: `configure_dual_export`, `attribution`, `ReveniumAttributionSpanProcessor`, `meter_tool_span`, `report_job_outcome`, `validate_connection`
- [ ] MLflow → Revenium OTLP dual export via supported MLflow/OpenTelemetry extension points, preserving Tracking Server export
- [ ] Idempotent configuration with actionable detection of post-initialization ordering errors
- [ ] OTEL GenAI semantic-convention output carrying model, provider, tokens (incl. cache), operation, finish reason, hierarchy, timing, error, environment, region
- [ ] Concurrency-safe dynamic attribution propagated onto each eligible child LLM span (sync, asyncio, concurrent)
- [ ] Tool metering to the Revenium Tool Events API, exactly once per logical execution, correlated to trace and job
- [ ] Job-outcome reporting correlated by externally supplied `agenticJobId`, using write-scope credentials and the documented outcome-reason field
- [ ] Feature-gated, default-disabled direct AI-completion fallback that cannot duplicate an OTLP completion
- [ ] Production HTTP behavior: timeouts, bounded jittered retries, `Retry-After`, idempotency preservation, credential redaction, configurable fail-open/fail-closed, bounded shutdown flush
- [ ] Documentation and runnable examples covering install, dual export, static/per-request/async attribution, tool metering, job outcomes, env vars, credential scopes, troubleshooting
- [ ] Full automated verification matrix (20 checks) proven with command output, using a fake OTLP collector and mocked Revenium HTTP server

### Out of Scope

- Forking or patching MLflow — the integration must work against stock MLflow via public extension points
- Calling Revenium production, customer environments, or any hosted write endpoint during development or testing — all tests use local fakes
- Accepting MLflow's LiteLLM-derived cost estimate as authoritative — Revenium is the rating source in this integration
- Publishing, releasing, pushing, or merging — build artifacts only
- Metering orchestration-only MLflow spans as AI completions — the backend already filters `execute_tool`/`invoke_agent`, and the SDK must not undo that
- A general observability framework — a small SDK abstraction is sufficient

## Context

**Repository placement (verified).** `revenium-mlflow-sdk/` was empty at initialization (`find . -mindepth 1 -not -path './.git*' | wc -l` → `0`); no instruction files, build config, or CI existed here. It sits alongside per-integration sibling SDKs in `~/Development/projects/revenium/`, and `revenium-litellm-proxy` establishes the one-repo-per-integration precedent. This repository is the correct home; conventions are inherited from siblings rather than from local files.

**Convention sources.** `revenium-python-sdk-internal` (PyPI `revenium-python-sdk`, package `revenium_middleware`) and `revenium-litellm-proxy`:

| Concern | Established convention |
|---|---|
| Build backend | `setuptools>=42` + `wheel`, `setuptools.build_meta` |
| HTTP client | `httpx` (`agentic_outcomes.py:23,73`) |
| Retry | Bounded, `Retry-After` honored with hard sleep cap (`agentic_outcomes.py:320-322`) |
| Idempotency | `Idempotency-Key` request header (`agentic_outcomes.py:180`) |
| Tests | pytest + pytest-asyncio; markers `unit` / `integration` / `e2e`; `addopts = -m 'not e2e and not integration'` |
| Lint / types | black, isort, mypy |
| Licence / authors | MIT, `Revenium <support@revenium.io>` |
| Repo files | README, CHANGELOG, CLAUDE.md, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, LICENSE, `docs/`, `examples/`, `tests/` |
| CI | `test.yml`, `e2e-tests.yml`, `pr-coverage-check.yml`, `secret-scan.yml` |

**Credential scopes (hard design decision, inherited).** `rev_mk_` metering keys are for completion and tool-event ingest only. `rev_sk_` write-scope keys are required for job creation and outcome reporting. Per `revenium-python-sdk-internal/CLAUDE.md` this is fixed, not a bug; documentation must state it explicitly and the SDK must fail clearly when a metering key is used for a write operation.

**Backend ingest contract (verified from `hypercurrent`, `origin/develop`, fetched 2026-09-04).**

- Metering service context path: `server.servlet.context-path=/meter` (`metering/src/main/resources/application.properties:1`)
- OTLP controller: `@RequestMapping(["/v2/otlp"])` with `@PostMapping("/v1/traces", consumes=["application/x-protobuf"])` at `OTLPController.kt:548` and a JSON variant at `:717`
- Advertised in `MeteringAuthOpenApiCustomizer.kt:106` as `/v2/otlp/v1/traces`
- Composed external route: `https://api.revenium.io/meter/v2/otlp/v1/traces`
- Corroborated by the shipping in-house SDK's sibling routes `/meter/v2/tool/events` and `/meter/v2/ai/completions` (`agentic_outcomes.py:46,50`), and job routes `/profitstream/v2/api/jobs[/{id}/outcome]` (`:205,229`)
- `/v1/traces` exists on `develop` only; the checked-out `enterprise` branch exposes logs and metrics only. Source-verified, **not** runtime-verified against `api.revenium.io`.

**Mapper selection (verified).** `GenAISemanticConventionMapper.canHandle` (`order()=100`) claims a payload when `gen_ai.provider.name` or `gen_ai.system` is present in resource **or first-span** attributes, and rejects `KNOWN_CUSTOM_SDK_NAMES`. MLflow with `MLFLOW_ENABLE_OTEL_GENAI_SEMCONV=true` satisfies this; `convertSpans` handles the trace path. The string `mlflow` appears nowhere in the backend, so the SDK must qualify on GenAI attributes, not on a provider name. The mapper header also documents server-side "filtering of non-LLM spans/logs (execute_tool, invoke_agent) to prevent double-counting".

**Attribution contract (verified).** All 21 required `revenium.*` attributes are recognized by the backend. Six additional recognized attributes are available for optional pass-through: `revenium.ticket.id`, `revenium.model.host`, `revenium.subscriber.email.source`, `revenium.system.fingerprint`, `revenium.subscription_tier`, `revenium.subscriber.credential.{name,value}`. `ReveniumAttributes.kt` enforces per-column caps (trace.name 256, trace.type 128, task.type 255, job.id 256, job.name 512, job.type 128, job.version 64, middleware.source 255, model.host 50, subscriber.email.source 20) and **drops** oversized values rather than truncating them — client-side validation is therefore worth having. Recognized `gen_ai.*` keys include both spellings of each token field (`input_tokens`/`prompt_tokens`, `output_tokens`/`completion_tokens`, `cache_read_tokens`/`cache_read_input_tokens`, `cache_creation_tokens`/`cache_creation_input_tokens`) and both `gen_ai.provider.name`/`gen_ai.system`.

**Local toolchain.** Python 3.9.6 (system), 3.11, 3.12 available; `uv` present. MLflow and `opentelemetry` are not installed — the sibling `mlflow/` directory is a bare `quickstart.py`, not a checkout, and resolved as a namespace package during probing.

**Known MLflow configuration surface.** `MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT=true`, `MLFLOW_ENABLE_OTEL_GENAI_SEMCONV=true`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf`, `OTEL_EXPORTER_OTLP_TRACES_HEADERS`. Exact behavior must be confirmed against the installed MLflow version, not from memory.

## Constraints

- **Tech stack**: Python `>=3.10`, `httpx`, `setuptools` build backend — follows the newer sibling (`revenium-litellm-proxy`) rather than the older `>=3.8` floor
- **Dependency**: depends on `revenium-python-sdk` for tool-event and job-outcome clients, retry, and idempotency — mirrors `revenium-litellm-guardrail`'s `revenium-python-sdk>=0.3.0` dependency; avoids reimplementing proven ingest logic
- **MLflow version floor**: determined empirically as the first release exposing every public API the SDK uses, proven by tests against installed versions — never selected from memory
- **Extension points**: public MLflow and OpenTelemetry APIs only; any unavoidable private MLflow API is isolated in one compatibility module with pinned, tested version bounds and a clear failure for unknown versions
- **Network**: no calls to Revenium production, customer environments, or any hosted write endpoint during development or testing; fake OTLP collector and mocked Revenium HTTP server only
- **Secrets**: no live credentials in code, fixtures, docs, examples, or generated artifacts; API keys and authorization headers redacted from logs and exceptions
- **Evidence**: no implementation, test, or compatibility claim without command output proving it; no claim of release, production readiness, publishing, CI success, merge readiness, or deployment
- **Delivery boundary**: build artifacts only — do not push, publish, release, or merge

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| This repository is the correct home for the SDK | Empty, purpose-named repo alongside per-integration sibling SDKs; `revenium-litellm-proxy` is precedent | — Pending |
| Depend on `revenium-python-sdk` rather than self-contained clients | Reuses proven httpx client, retry/`Retry-After`, idempotency, and existing tool-event/job-outcome implementations; matches `revenium-litellm-guardrail` precedent; less new code to prove | — Pending |
| Default OTLP traces endpoint `https://api.revenium.io/meter/v2/otlp/v1/traces` | Route composed from backend source: `/meter` context path + `/v2/otlp` mapping + `/v1/traces` POST, advertised in the OpenAPI customizer; corroborated by shipping sibling routes. Remains overridable | — Pending (source-verified, not runtime-verified) |
| Python floor `>=3.10` | Follows the newer sibling; modern typing available; local toolchain can exercise 3.10–3.12 | — Pending |
| Build the completion fallback, feature-gated and disabled by default | Delivers the capability while honoring the exactly-once decision rule; OTLP trace ingest is source-verified to handle eligible spans, so fallback is a safety net rather than the primary path | — Pending |
| `revenium.middleware.source` defaults to `mlflow` | Identifies MLflow-sourced records in Revenium; `middleware.source` is a recognized pass-through marker capped at 255 chars | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Business Context check — customer, revenue model, success metric still accurate?
4. Audit Out of Scope — reasons still valid?
5. Update Context with current state

---
*Last updated: 2026-09-04 after initialization*
