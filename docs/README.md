# Documentation

This index lists the current and planned documentation for the Revenium MLflow SDK. Most guides are
scheduled for a later development phase; their planned locations are listed here so other documents
can link to them consistently.

## Available now

[`verification/`](verification/) holds captured command output backing every build, install,
compatibility, and behavioural claim this repository makes. Each file is a transcript, not a
description of one: the fenced blocks are verbatim stdout and stderr of the command shown
immediately above them.

Several of these documents exist to show a check **failing** as well as passing. A guard that has
never been observed to go red proves nothing, so where a document claims one, it carries the
plant-and-revert transcript alongside the green one.

### Phase 01 — packaging, typed surface, and the `_compat` wall

| Document | What it proves |
|---|---|
| [`pkg-02-build-install.md`](verification/pkg-02-build-install.md) | Wheel and sdist build, `py.typed` present in both artifacts, clean-environment install, PEP 503 normalized name resolution, concurrent-install determinism, and the editable install |
| [`ver-06-gate.md`](verification/ver-06-gate.md) | Formatting, linting, and strict type checking pass — behind a gate shown able to fail, since a check configured so it cannot fail also produces a green transcript |
| [`ver-07-version-matrix.md`](verification/ver-07-version-matrix.md) | The suite run across four interpreter-and-MLflow combinations, with the resolved version printed on each leg |
| [`ver-08-plant-and-revert.md`](verification/ver-08-plant-and-revert.md) | The private-access wall detecting a real planted breach, not merely reporting a clean tree |
| [`pkg-09-import-purity.md`](verification/pkg-09-import-purity.md) | Importing the SDK opens no socket and installs no global tracing state |

### Phase 02 — span eligibility and GenAI semantic conventions

| Document | What it proves |
|---|---|
| [`sem-05-cache-token-ab.md`](verification/sem-05-cache-token-ab.md) | MLflow *collects* prompt-cache token counts and its own OTLP translator discards them — the side-by-side A/B that is a large part of why this SDK exists |

### Phase 03 — attribution context and span processor

| Document | What it proves |
|---|---|
| [`attr-02-stamp-time.md`](verification/attr-02-stamp-time.md) | A span's eligibility is not knowable when `on_start` runs, measured across all three MLflow span-creation paths; and that an attribute written in `on_end` is lost with a single log line as the only signal |

### Phase 04 — Revenium-owned OTLP export and the install gate

| Document | What it proves |
|---|---|
| [`exp-03-dual-export.md`](verification/exp-03-dual-export.md) | One MLflow trace reaching both a Tracking Server store and an OTLP collector in a single run, asserted on the decoded protobuf rather than on a mock call |

### Fixes verified outside a phase

| Document | What it proves |
|---|---|
| [`cr-01-provider-cap.md`](verification/cr-01-provider-cap.md) | The emitted provider value shown unbounded — reaching the billing wire at any length — and then bounded, with the boundary asserted on both sides |

## Planned

These guides are planned but not yet present:

| Document | Will cover |
|---|---|
| Getting started | Installing the SDK into an application already instrumented with MLflow tracing, and the first configured export |
| Configuration reference | Every configuration field, its default, and the environment variable that sets it |
| Attribution reference | The `revenium.*` span attribute keys, their value caps, and the exported constants that spell them |
| Tool metering and job outcomes | Metering a tool span and reporting a job outcome, including idempotency |
| Compatibility | The supported MLflow range, how the capability probe behaves, and what an unsupported version reports |
| Troubleshooting | Diagnosing a missing or empty export, and reading the connection diagnostics |
| Migration | Moving from MLflow's built-in dual export to SDK-owned export |

## Conventions for these documents

Claims about builds, installation, or interoperability require a supporting transcript in
`verification/`. Do not add one without captured command output.

The package is not published to any package index, and CI has not run for it. Do not describe it as
released, published, production-ready, or CI-verified.

Documentation examples must use obviously fake placeholder values and local fakes. See
[SECURITY.md](../SECURITY.md).

This SDK is a Revenium product built on MLflow's public extension points. It is neither part of nor
endorsed by the MLflow project. The documentation must keep that distinction clear.
