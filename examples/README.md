# Examples

Runnable examples are planned for the documentation phase. This directory reserves a stable path
for links from the README and documentation index.

## The rule every example follows

Every example must run against local fakes. Examples must not send traffic to Revenium production, a
customer environment, or any hosted write endpoint. They must not contain live credentials.

This rule protects billing correctness as well as security. Because the SDK sits on the billing
path, an example that reaches a live ingest endpoint could create chargeable data.

Examples may use:

- A fake OTLP collector on `localhost` — stdlib `http.server` bound to port 0. The OTLP exporter
  uses `requests`, so httpx-level mocking cannot intercept it and a real local listener is needed.
- `respx` to intercept the `httpx` calls the SDK makes directly.
- The `dry_run=` parameter that `revenium-python-sdk` exposes on every write path.
- Obviously fake placeholder credentials, read from the environment with a fake default.

## Planned examples

| Example | Will show |
|---|---|
| Minimal export | Configuring export against a local collector and seeing an attributed span arrive |
| Attribution | Stamping organization, subscriber, and product attribution onto traced calls |
| Tool metering | Metering a tool span end to end |
| Job outcomes | Creating a job and reporting its outcome |
| Diagnostics | Validating a connection and reading the diagnostics it returns |

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup and
[SECURITY.md](../SECURITY.md) for the full statement of the two hard rules.
