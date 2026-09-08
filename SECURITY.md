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

Two rules are absolute because this SDK sits on the billing path. It carries the attribution used to
calculate customer charges and holds credentials that can write metering data.

### 1. No live credentials, anywhere

No API key, authorization header, bearer token, or other live credential may appear in source code,
test fixtures, documentation, examples, or any generated or captured artifact, including the
evidence transcripts under `docs/verification/`.

Use obviously fake placeholder values in anything committed. Read real credentials from the
environment at runtime only. Where a credential could reach a log or an exception message, redact
it. An API key in a stack trace is exposed to everyone who can read the logs.

Removing a live credential in a later commit does not remove it from git history. Treat the
credential as compromised and rotate it.

### 2. No calls to Revenium production, or to any hosted write endpoint

Tests, examples, and development workflows must not send traffic to Revenium production, a customer
environment, or any hosted write endpoint. A test that reaches a live ingest endpoint can corrupt
real billing data.

Use local fakes instead:

- A fake OTLP collector on `localhost` (stdlib `http.server` bound to port 0) for span export. The
  OTLP exporter uses `requests`, so httpx-level mocking cannot intercept it.
- `respx` for the `httpx` calls the SDK makes directly.
- The `dry_run=` parameter that `revenium-python-sdk` exposes on every write path.

## Reporting a suspicious dependency

If a declared dependency fails to install or its name looks wrong, do not substitute a package with
a similar name or try a different spelling. The dependency may be typosquatted or nonexistent.
Report it to `support@revenium.io` instead.

## Scope

This policy covers the `revenium-mlflow` distribution and this repository. Vulnerabilities in MLflow
itself belong to the MLflow project; this SDK is an independent integration and is neither part of,
nor endorsed by, that project.
