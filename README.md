[![Revenium MLflow SDK — Revenium Labs](assets/mlflow-revenium-labs.png)](assets/mlflow-revenium-labs.png)

[![Revenium Labs](https://img.shields.io/badge/Revenium-Labs-6f42c1?style=for-the-badge)](https://github.com/revenium/.github/blob/main/LABS.md) [![Status: Early development](https://img.shields.io/badge/status-early%20development-f0a020?style=for-the-badge)](#status)

# Revenium MLflow SDK

**Revenium-supported economic telemetry for MLflow-instrumented applications.**

`revenium-mlflow` lets an application that already uses MLflow tracing send attribution, tool
metering, and job-outcome signals to Revenium — without forking MLflow, without modifying it, and
without double-counting a single model call, tool execution, or job outcome. Traces stay in your
MLflow Tracking Server, which remains the engineering system of record for tracing, evaluation, and
experiments. Revenium becomes the authoritative rating source for the economics of those same
traces.

> ### 🧪 This is a Revenium Labs project
>
> **Revenium Labs** projects are field-developed, best-effort, beta-quality software shared in the open. They are **not** part of Revenium's officially supported products.
>
> * It may need adaptation for your environment.
> * It's provided as-is, without the versioned-release guarantees, SLAs, or formal support that back our core products.
> * Issues, feedback, and PRs are welcome. [Join us on Discord](https://discord.gg/J2DbmjZ2nA).
>
> → **[What is Revenium Labs?](https://github.com/revenium/.github/blob/main/LABS.md)**

> This is a Revenium project. It is **neither part of, nor endorsed by, the MLflow project.**
> MLflow is a trademark of its respective owners; this SDK is an independent integration built
> entirely on MLflow's public extension points.

## Who this is for

Teams already running MLflow tracing against an MLflow Tracking Server who want Revenium cost
attribution, spend controls, and job ROI computed from the traces they are already producing.

## Status

Early development — earlier than the "beta" that Revenium Labs projects usually carry. This
distribution is **not published to any package index**, and nothing here should be read as a claim
of release or production readiness. Install it from a locally built artifact or from the working
tree.

## Install

Requires Python 3.10 or newer.

```bash
# From the working tree (editable, with the development extra)
uv venv --python 3.10 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

# Or from a locally built wheel
.venv/bin/python -m build
uv pip install --python .venv/bin/python dist/revenium_mlflow-*.whl
```

Verify the install:

```bash
.venv/bin/python -c "import revenium_mlflow; print(revenium_mlflow.__version__)"
```

The captured transcript for the build, the clean-environment install, and the editable install is
committed at [`docs/verification/pkg-02-build-install.md`](docs/verification/pkg-02-build-install.md).

## Typing

The distribution is PEP 561 typed: it ships a `py.typed` marker, so type checkers consume the
package's inline annotations directly with no stub package required.

## Requirements

| Dependency | Constraint | Why |
|---|---|---|
| Python | `>=3.10` | Lowest floor the whole dependency graph supports |
| `mlflow` | `>=3.15.0,<4` | First release exposing `mlflow.tracing.get_bridged_tracer_provider()`, the public `SpanProcessor` attachment point |
| `opentelemetry-api` / `-sdk` | `>=1.30.0,<2` | MLflow's declared `>=1.9.0` floor is not usable — 1.9.0 requires `pkg_resources` and fails to import |
| `opentelemetry-exporter-otlp-proto-http` | `>=1.30.0,<2` | Revenium's ingest route is HTTP + protobuf; the gRPC exporter is deliberately not used |
| `revenium-python-sdk` | `>=0.7.0,<1` | Tool events, job outcomes, retry, and idempotency |
| `httpx` | `>=0.27,<1` | Direct Revenium HTTP calls |

## Documentation

See [`docs/`](docs/README.md) for the documentation index and [`examples/`](examples/README.md) for
runnable examples.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports go to `support@revenium.io` — see
[SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
