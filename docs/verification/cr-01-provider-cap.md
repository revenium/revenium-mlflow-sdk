# CR-01 — the emitted provider value, shown unbounded and then bounded

Captured evidence for the quick task `260906-cr-01-bound-provider`. Every block below is the
verbatim stdout and stderr of the command shown above it, run on this machine in one session.

**What this file has to prove.** CR-01 is that `map_span` wrote `infer_provider(span)` to
`gen_ai.provider.name` and `gen_ai.system` with no length constraint, so an
application-controlled `mlflow.llm.provider` — or a bridged instrumentor's own
`gen_ai.provider.name` — reached the billing wire verbatim at any length. A fix whose tests were
never seen red proves nothing about the fix, so section 1 is the tests failing against the
**unmodified** source and section 2 is the same tests passing after the one-line change. Sections
3 and 4 are what stops section 2 from being green for the wrong reason: the whole gate, and the
suite counts before and after.

**Scope and boundaries.**

- **No CI has run.** Every transcript below was produced by running the command shown, locally.
  Nothing here is a CI result, a release, a publication, a merge, or a statement about production
  readiness.
- **The credential is synthetic.** `rev_sk_SUPERSECRET_KEY` is transcribed from the reproduction
  in `02-REVIEW.md`, which was itself synthetic. No live key exists in this file, in the test that
  carries it, or in any fixture. No command reads or prints an environment variable.
- No command contacts Revenium, a customer environment, or any hosted endpoint. The commands that
  import MLflow are the test runs, and `tests/conftest.py` disables MLflow's own outbound
  telemetry for the whole session before any test imports it.
- Every command runs under `.venv/bin/python`, the same interpreter `scripts/check.sh` resolves as
  `PY`. The system `python3` on this machine is 3.9.6, below this project's 3.10 floor, so a bare
  PATH lookup would make these transcripts unattributable.

**Environment.** macOS, arm64. Interpreter `Python 3.10.20` at `.venv/bin/python`.

**Which tests can go red, and which are standing assertions.** Four of the nine node ids added
fail in section 1: the over-cap boundary on both source paths, the credential absence, and the
no-drift check. The other five cannot fail against the shipped code and are not defective for it —
the at-cap half of the boundary pair is what proves the fix is a boundary rather than a blanket
drop, the never-empty assertion reds only against a *future* change from substitution to
omission, and the sentinel-length assertion pins arithmetic the fallback depends on. A pair where
only one side can red is a cap asserted from one direction, which is the failure mode the pair
exists to rule out.

---

## 1. Red — the new tests against the unmodified `semconv.py`

Run at commit `db00875`, with `tests/unit/test_semconv_provider.py` edited and no source file
touched.

```console
$ .venv/bin/python -m pytest tests/unit/test_semconv_provider.py -q
..............................................FF..F.F..........          [100%]
=================================== FAILURES ===================================
_ test_a_provider_one_character_over_the_cap_becomes_the_sentinel[step1-mlflow-llm-provider] _

factory = <function _step_one_provider_span at 0x107490040>

    @pytest.mark.parametrize("factory", _PROVIDER_SOURCE_PATHS)
    def test_a_provider_one_character_over_the_cap_becomes_the_sentinel(
        factory: Callable[[str], ReadableSpan],
    ) -> None:
        """One code point over, and both spellings carry step 5's answer instead.
    
        This is the half that makes the pair a cap rather than no cap at all. An
        over-cap string is not a provider name — it is an unbounded blob sitting in
        a provider-shaped attribute — so it takes the answer the chain already
        declares for "no provider I can name" (D-CR01).
        """
        over_cap = "p" * (_MAX_EMITTED_VALUE_CHARS + 1)
    
        attributes = map_span(factory(over_cap)).attributes
    
>       assert (attributes["gen_ai.provider.name"], attributes["gen_ai.system"]) == (
            PROVIDER_SENTINEL,
            PROVIDER_SENTINEL,
        )
E       AssertionError: assert ('ppppppppppp...pppppppppppp') == ('revenium-un...own-provider')
E         
E         At index 0 diff: 'ppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppp' != 'revenium-unknown-provider'
E         Use -v to get more diff

tests/unit/test_semconv_provider.py:579: AssertionError
_ test_a_provider_one_character_over_the_cap_becomes_the_sentinel[step2-gen-ai-provider-name] _

factory = <function _step_two_provider_span at 0x1074900d0>

    @pytest.mark.parametrize("factory", _PROVIDER_SOURCE_PATHS)
    def test_a_provider_one_character_over_the_cap_becomes_the_sentinel(
        factory: Callable[[str], ReadableSpan],
    ) -> None:
        """One code point over, and both spellings carry step 5's answer instead.
    
        This is the half that makes the pair a cap rather than no cap at all. An
        over-cap string is not a provider name — it is an unbounded blob sitting in
        a provider-shaped attribute — so it takes the answer the chain already
        declares for "no provider I can name" (D-CR01).
        """
        over_cap = "p" * (_MAX_EMITTED_VALUE_CHARS + 1)
    
        attributes = map_span(factory(over_cap)).attributes
    
>       assert (attributes["gen_ai.provider.name"], attributes["gen_ai.system"]) == (
            PROVIDER_SENTINEL,
            PROVIDER_SENTINEL,
        )
E       AssertionError: assert ('ppppppppppp...pppppppppppp') == ('revenium-un...own-provider')
E         
E         At index 0 diff: 'ppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppp' != 'revenium-unknown-provider'
E         Use -v to get more diff

tests/unit/test_semconv_provider.py:579: AssertionError
______ test_the_credential_marker_reaches_neither_emitted_provider_value _______

    def test_the_credential_marker_reaches_neither_emitted_provider_value() -> None:
        """CR-01 itself: the 264-code-point reproduction no longer goes to the wire.
    
        The leak was duplicated across both spellings, so both are swept. A test
        over one key would pass while the other kept exporting the credential.
        """
        attributes = map_span(_step_one_provider_span(_CREDENTIAL_PROVIDER)).attributes
        emitted = (attributes["gen_ai.provider.name"], attributes["gen_ai.system"])
    
>       assert not any(_CREDENTIAL_MARKER in str(value) for value in emitted)
E       assert not True
E        +  where True = any(<generator object test_the_credential_marker_reaches_neither_emitted_provider_value.<locals>.<genexpr> at 0x107422960>)

tests/unit/test_semconv_provider.py:626: AssertionError
_____ test_an_over_cap_provider_emits_what_no_provider_signal_at_all_emits _____

    def test_an_over_cap_provider_emits_what_no_provider_signal_at_all_emits() -> None:
        """One spelling of "unknown", not two, so the two paths cannot drift apart.
    
        If the rejection path grew its own literal, one customer's spans would split
        across two provider labels — each reading as correct forever, and neither
        discoverable from the client side. This is drift 4 applied to the new path.
        """
        rejected = map_span(_step_one_provider_span("p" * (_MAX_EMITTED_VALUE_CHARS + 1))).attributes
        absent = map_span(_admitted_span_with_no_provider_signal()).attributes
    
>       assert rejected["gen_ai.provider.name"] == absent["gen_ai.provider.name"]
E       AssertionError: assert 'pppppppppppp...ppppppppppppp' == 'revenium-unknown-provider'
E         
E         - revenium-unknown-provider
E         + ppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppppp

tests/unit/test_semconv_provider.py:649: AssertionError
=========================== short test summary info ============================
FAILED tests/unit/test_semconv_provider.py::test_a_provider_one_character_over_the_cap_becomes_the_sentinel[step1-mlflow-llm-provider]
FAILED tests/unit/test_semconv_provider.py::test_a_provider_one_character_over_the_cap_becomes_the_sentinel[step2-gen-ai-provider-name]
FAILED tests/unit/test_semconv_provider.py::test_the_credential_marker_reaches_neither_emitted_provider_value
FAILED tests/unit/test_semconv_provider.py::test_an_over_cap_provider_emits_what_no_provider_signal_at_all_emits
4 failed, 59 passed in 0.08s
```

`4 failed, 59 passed`. Each failure is the emitted value arriving whole where the sentinel was
expected — the defect, measured through the public `map_span` boundary, on both the step-1
(MLflow, JSON-encoded) and step-2 (bridged instrumentor, bare) source paths.

---

## 2. Green — the same tests after the one-line fix

The change is `provider = _bounded(infer_provider(span)) or PROVIDER_SENTINEL` at the single
emission site, plus two corrected docstrings. No test was changed between sections 1 and 2.

```console
$ .venv/bin/python -m pytest tests/unit/test_semconv_provider.py -q
...............................................................          [100%]
63 passed in 0.04s
```

---

## 3. The full gate

`scripts/check.sh` runs under `set -euo pipefail` and aborts at the first non-zero command, so a
transcript that reaches `all checks passed` is a transcript in which all four steps ran.

```console
$ bash scripts/check.sh
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
59 files already formatted
### .venv/bin/python -m ruff check .
All checks passed!
### .venv/bin/python -m mypy --strict src/revenium_mlflow
Success: no issues found in 16 source files
### .venv/bin/python -m pytest -q
........................................................................ [ 17%]
........................................................................ [ 35%]
........................................................................ [ 53%]
........................................................................ [ 71%]
........................................................................ [ 89%]
..........................................                               [100%]
402 passed in 1.24s
### all checks passed
```

Exit status `0`.

---

## 4. Suite counts, before and after

The "393 plus the tests this task added, nothing removed" claim, shown rather than asserted. The
first run is at commit `db00875`, before any file was edited; the second is at the tree section 3
was run against.

```console
$ .venv/bin/python -m pytest -q --collect-only 2>&1 | tail -3   # at db00875, pre-change
tests/unit/test_spanattrs.py::test_the_fixture_value_decodes_through_the_shared_decoder

393 tests collected in 0.08s
```

```console
$ .venv/bin/python -m pytest -q --collect-only 2>&1 | tail -2   # after

402 tests collected in 0.06s
```

393 to 402: the nine node ids the boundary tests add, and nothing else. That the count rose is not
by itself evidence that nothing was removed — a deleted test and an added one cancel — so the
deletion is gated separately. Zero `def test_` lines were removed or renamed by this task, measured
against its base commit and covering every file it touched:

```console
$ git diff -U0 db00875 -- tests/ | grep '^-' | grep -c 'def test_'
0
```

---

## What is not fixed here

Deliberately out of scope, each logged in `.planning/todos/pending/` and unmodified by this task:

- **CR-02** — `error.type` forwards `exception.type` verbatim and unbounded. `_bounded`'s
  docstring now names it as uncovered rather than implying the cap reaches it.
- **CR-03** — a JSON-encoded empty declared operation rejecting a span the recorded 02-07
  checkpoint decision says should be admitted.
- **WR-01** — `_clean_reason`.

A sub-cap provider string is still forwarded verbatim, which SEM-01 requires: an allowlist there
would drop every provider this SDK has not heard of. That is the accepted residual T-02-08-07,
now recorded against the provider keys in `tests/unit/test_semconv_allowlist.py` rather than left
unclassified — which is the omission that let CR-01 survive review in the first place.
