# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `scripts/version_matrix.sh` — the version matrix, and the single definition of it. Four legs: the
  declared MLflow floor, a median 3.x and the newest 3.x resolved at run time, each on the Python
  3.10 floor, plus the newest MLflow on Python 3.14. Every leg pins its interpreter, prints the
  interpreter and `mlflow.__version__` it actually ran under, and fails if either is not the one the
  leg exists to test. Captured evidence at `docs/verification/ver-07-version-matrix.md`.
- `.github/workflows/version-matrix.yml` — a workflow file that invokes that same script, added as
  provision for a future push. **It has never been executed in this project**, and no hosted build
  service has run anything for this repository; this entry records that a file was written, not that
  anything ran. It holds a read-only contents scope, triggers on pull request and manual dispatch
  only, and carries no step that uploads an artifact, creates a release, pushes a tag, or merges.

### Changed

- `uv.lock` is now ignored rather than left uncovered by `.gitignore`. This distribution is a
  library: its correctness claim is that anything inside its declared floors resolves and works, and
  the version matrix substantiates that by resolving independently on every leg. Tracking one
  resolution would pin what the matrix has to vary. Consumers get reproducibility from their own
  lockfile resolved over these floors.

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
