# Documentation

This index lists the current and planned documentation for the Revenium MLflow SDK. Most guides are
scheduled for a later development phase; their planned locations are listed here so other documents
can link to them consistently.

## Available now

| Path | Contents |
|---|---|
| [`verification/`](verification/) | Captured command output backing every build, install, and compatibility claim this repository makes |
| [`verification/pkg-02-build-install.md`](verification/pkg-02-build-install.md) | Build of the wheel and sdist, `py.typed` in both artifacts, clean-environment install, PEP 503 normalized name resolution, concurrent-install determinism, and the editable install |

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
