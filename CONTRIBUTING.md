# Contributing

Thank you for your interest in contributing to the Revenium MLflow SDK.

## Development setup

This project's floor is Python 3.10 and the toolchain is [uv](https://docs.astral.sh/uv/).

Do not use a bare `python3`. On many machines — including the one this project was developed on —
`python3` resolves to a below-floor interpreter (3.9), and a below-floor interpreter will build an
artifact that is silently mislabelled. Every command below pins the interpreter explicitly.

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

`scripts/check.sh` is the single command that runs the whole gate. It is added in a later plan of
the current phase; until then, run `pytest` directly.

## Building artifacts

```bash
.venv/bin/python -m build
```

This produces a wheel and an sdist under `dist/`. **Do not publish, tag, or push a release.** The
delivery boundary for this project is build artifacts only.

## Test markers

| Marker | Meaning | In the default run? |
|---|---|---|
| `unit` | Fast, no external dependencies, no network | Yes |
| `integration` | Requires a running service such as a fake collector or a tracking server | No |
| `e2e` | End-to-end against live services | No |

Mark every test. An unmarked test still runs by default, but the markers are what let CI select a
subset, and an unmarked slow test is the one that makes the fast suite stop being fast.

## Hard rules

These are not style preferences. See [SECURITY.md](SECURITY.md) for the full statement.

1. **No live credentials** in code, fixtures, docs, examples, or captured artifacts. Placeholders in
   anything committed; real values from the environment at runtime; redacted in logs and exceptions.
2. **No calls to Revenium production, a customer environment, or any hosted write endpoint** from
   tests or examples. Use a local fake OTLP collector, `respx` for `httpx`, and the
   `dry_run=` parameter `revenium-python-sdk` provides.

## Evidence

This repository does not accept a compatibility, build, or install claim without the command output
that proves it. Captured transcripts live in `docs/verification/`. If you change something a
transcript asserts, re-run the commands and update the transcript in the same change.

Equally: do not describe the package as released, published, production-ready, or CI-verified. None
of those are true today, and a document that says otherwise is a bug.

## Pull requests

- Keep changes focused; one concern per commit
- Follow the existing code style; the gate is enforced by `scripts/check.sh`, not by review
- Add tests for new behavior, and update `CHANGELOG.md` under `## [Unreleased]`
- Update documentation when behavior changes

## Questions

Check existing issues first. For bugs, open an issue with reproduction steps. For anything else,
email `support@revenium.io`.
