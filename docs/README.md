# Documentation

Index of the documentation sets for the Revenium MLflow SDK. Most guide pages are written in a later
phase; this page names them now so their eventual location is fixed and linkable.

## Available now

| Path | Contents |
|---|---|
| [`verification/`](verification/) | Captured command output backing every build, install, and compatibility claim this repository makes |
| [`verification/pkg-02-build-install.md`](verification/pkg-02-build-install.md) | Build of the wheel and sdist, `py.typed` in both artifacts, clean-environment install, PEP 503 normalized name resolution, concurrent-install determinism, and the editable install |

## Planned

Written in the documentation phase, not yet present:

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

**Evidence over assertion.** Anything stated here about what builds, installs, or interoperates is
backed by a transcript in `verification/`. A claim without captured output proving it does not
belong in this directory.

**No release language.** This package is not published to any package index and no CI has run for
it. Documentation must not describe it as released, published, production-ready, or CI-verified.

**No live credentials.** Examples in documentation use obviously fake placeholder values and run
against local fakes. See [SECURITY.md](../SECURITY.md).

**Not an MLflow project document.** This SDK is a Revenium product, built entirely on MLflow's
public extension points. It is neither part of, nor endorsed by, the MLflow project, and its
documentation should not read as though it were.
