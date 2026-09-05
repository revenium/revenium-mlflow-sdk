# Examples

Runnable examples land in the documentation phase. This directory is created now so their location
is fixed and referenceable from the README and the docs index.

## The rule every example follows

**Every example runs against local fakes only.** No example sends traffic to Revenium production, to
a customer environment, or to any hosted write endpoint, and no example contains a live credential.

This is a correctness rule as much as a security one: this SDK sits on the billing path, so an
example that writes to a live ingest endpoint does not merely leak — it writes billing data that
someone is charged for.

Concretely, an example may use:

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
