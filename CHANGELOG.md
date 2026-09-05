# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0]

Initial packaging of the Revenium MLflow SDK. **Not released and not published to any package
index** — this entry records the version the distribution metadata declares, not a release event,
and the section is deliberately undated for that reason.

### Added

- `revenium-mlflow` distribution with import package `revenium_mlflow`, built with the
  `setuptools.build_meta` backend under a `setuptools>=77` build requirement. The 77 floor is
  required by the PEP 639 `license = "MIT"` string form, which fails to build on 76.1.0 and earlier.
- Declared runtime floors: `mlflow>=3.15.0,<4` — 3.15.0 is the first release exposing
  `mlflow.tracing.get_bridged_tracer_provider()`, the public `SpanProcessor` attachment point, and
  the `<4` bound guards the major version where a public-API break is likely while letting every
  3.x land immediately. Also `opentelemetry-api`, `opentelemetry-sdk` and
  `opentelemetry-exporter-otlp-proto-http` at `>=1.30.0,<2`, `revenium-python-sdk>=0.7.0,<1`, and
  `httpx>=0.27,<1`.
- PEP 561 typed distribution: a `py.typed` marker shipped into both the wheel and the sdist via
  `[tool.setuptools.package-data]`, with the package discovered by
  `[tool.setuptools.packages.find] where = ["src"]`.
- `dev` optional-dependency extra: `pytest`, `pytest-asyncio`, `respx`, `mypy`, `build`, `pyyaml`.
- Repository convention file set: `README.md`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, plus `docs/`, `examples/` and `tests/`.
- pytest configuration with the `unit` / `integration` / `e2e` marker scheme; the default run
  deselects `integration` and `e2e` so it needs no live services.
- Captured build-and-install evidence at `docs/verification/pkg-02-build-install.md`.

### Notes

- The SDK is a Revenium product. It is neither part of, nor endorsed by, the MLflow project.
- No CI has run for this version. No artifact has been uploaded, tagged, or pushed.

[Unreleased]: https://github.com/revenium/revenium-mlflow/compare/main...HEAD
