# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this package, report it to us privately.

**DO NOT** open a public GitHub issue for a security vulnerability.

### How to report

Email: **support@revenium.io**

Please include:

- Package name and version
- A description of the vulnerability
- Steps to reproduce, if applicable
- Potential impact
- A suggested fix, if you have one

We review and respond to security reports in a timely manner.

## Rules for contributors

Two rules are absolute in this repository. Both exist because this SDK sits on the billing path: it
carries the attribution that decides what a customer is charged, and it holds credentials scoped to
write metering data.

### 1. No live credentials, anywhere

No API key, authorization header, bearer token, or other live credential may appear in source code,
test fixtures, documentation, examples, or any generated or captured artifact — including the
evidence transcripts under `docs/verification/`.

Use obviously fake placeholder values in anything committed. Read real credentials from the
environment at runtime only. Where a credential could reach a log or an exception message, redact
it; an API key that reaches a stack trace has been disclosed to everyone who can read the logs.

A commit that adds a live credential is not fixed by a follow-up commit that removes it — the value
remains in git history and must be treated as compromised and rotated.

### 2. No calls to Revenium production, or to any hosted write endpoint

Tests, examples, and development workflows must not send traffic to Revenium production, to a
customer environment, or to any hosted write endpoint. This is not only a security rule: a test that
writes to a live ingest endpoint corrupts real billing data.

Use local fakes instead:

- A fake OTLP collector on `localhost` (stdlib `http.server` bound to port 0) for span export. The
  OTLP exporter uses `requests`, so httpx-level mocking cannot intercept it.
- `respx` for the `httpx` calls the SDK makes directly.
- The `dry_run=` parameter that `revenium-python-sdk` exposes on every write path.

## Reporting a suspicious dependency

If a declared dependency fails to install or its name looks wrong, do not substitute a
similarly-named package and do not retry with a different spelling. A failed install can indicate a
typosquatted or hallucinated package name, and installing the nearest match is how that attack
succeeds. Report it to `support@revenium.io` instead.

## Scope

This policy covers the `revenium-mlflow` distribution and this repository. Vulnerabilities in MLflow
itself belong to the MLflow project; this SDK is an independent integration and is neither part of,
nor endorsed by, that project.
