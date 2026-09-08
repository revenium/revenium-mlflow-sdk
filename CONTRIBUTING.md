# Contributing

This guide covers local setup, repository checks, and the rules for contributing to the Revenium
MLflow SDK.

## Development setup

This project's floor is Python 3.10 and the toolchain is [uv](https://docs.astral.sh/uv/).

Do not use a bare `python3`. On many machines, including the one used to develop this project, it
resolves to Python 3.9. That interpreter is below the supported floor and can produce a mislabelled
artifact. The commands below pin the interpreter explicitly.

```bash
# Create the development environment. --clear makes this idempotent: without it,
# `uv venv` exits non-zero the second time you run it, because .venv already exists.
uv venv --python 3.10 --clear .venv

# Install the package in editable mode with the development extra
uv pip install --python .venv/bin/python -e ".[dev]"

# Confirm the install
.venv/bin/python -c "import revenium_mlflow; print(revenium_mlflow.__version__)"
```

`.venv/`, `dist/`, `build/` and `*.egg-info/` are gitignored. Nothing from your working tree outside
`src/revenium_mlflow/` is swept into a built artifact.

## Running the checks

```bash
# Tests. The default run deselects the `integration` and `e2e` markers,
# so it needs no live services.
.venv/bin/python -m pytest

# The full gate — lint, format, and type checks together with the tests
./scripts/check.sh
```

`scripts/check.sh` runs the complete gate. It is scheduled for a later development phase. Until it
is present, run `pytest` directly.

## Building artifacts

```bash
.venv/bin/python -m build
```

This produces a wheel and an sdist under `dist/`. **Do not publish, tag, or push a release.** This
project currently delivers build artifacts only.

## Test markers

| Marker | Meaning | In the default run? |
|---|---|---|
| `unit` | Fast, no external dependencies, no network | Yes |
| `integration` | Requires a running service such as a fake collector or a tracking server | No |
| `e2e` | End-to-end against live services | No |

Mark every test. Unmarked tests still run by default, but CI uses markers to select subsets. A slow,
unmarked test also slows the default suite.

## Hard rules

These are not style preferences. See [SECURITY.md](SECURITY.md) for the full statement.

1. **No live credentials** in code, fixtures, docs, examples, or captured artifacts. Placeholders in
   anything committed; real values from the environment at runtime; redacted in logs and exceptions.
2. **No calls to Revenium production, a customer environment, or any hosted write endpoint** from
   tests or examples. Use a local fake OTLP collector, `respx` for `httpx`, and the
   `dry_run=` parameter `revenium-python-sdk` provides.

## Evidence

Compatibility, build, and installation claims require supporting command output. Captured
transcripts live in `docs/verification/`. If a change invalidates a transcript, re-run its commands
and update the transcript in the same change.

Do not describe the package as released, published, production-ready, or CI-verified. None of those
claims is currently true.

## Pull requests

- Keep changes focused, with one concern per commit.
- Follow the existing code style. `scripts/check.sh`, rather than reviewer preference, defines the gate.
- Add tests for new behavior and update `CHANGELOG.md` under `## [Unreleased]`.
- Update the documentation when behavior changes.

## Questions

Check existing issues first. For bugs, open an issue with reproduction steps. For anything else,
email `support@revenium.io`.
