"""SEM-05 criterion 2: the one difference this SDK exists for, shown side by side.

**The claim.** MLflow *collects* cache tokens. ``TokenUsageKey`` declares
``cache_read_input_tokens`` and ``cache_creation_input_tokens`` identically at
the 3.15.0 floor and at 3.16.0, and six integration modules populate them. Only
its **OTLP translator** discards them: ``_translate_universal_attributes`` reads
``input_tokens`` and ``output_tokens`` out of ``mlflow.chat.tokenUsage`` and
nothing else (``translator.py:115-121``, identical at both versions). So a
prompt-caching customer's cached tokens never reach Revenium through MLflow's
own export path, and no error appears on either side — the span arrives, it is
accepted, and the cheapest tokens in the invoice are simply not there.

**Why one test and not two.** Two tests that each pass show a reader nothing.
The comparison is therefore a single test that feeds the *identical span object*
to both mappers and prints both usage-attribute dicts on two labelled lines in
one captured output, so the difference is visible rather than inferred from two
green checkmarks. That captured output is committed as
:data:`_TRANSCRIPT`, and ``test_the_transcript_records_this_runs_side_by_side_output``
below re-derives both lines and requires the committed file to still contain
them — the file is a capture of a run, not a document describing one.

**The MLflow import is live and unguarded (D-03).** No ``pytest.importorskip``,
no ``try``/``except ImportError``, and no frozen snapshot of the translator's
output standing in for it. A snapshot stops being evidence about the *installed*
MLflow and becomes evidence about a file we wrote; a skip guard lets this
criterion quietly stop being proven while the suite stays green. If MLflow moves
the module, this test errors loudly, which is the correct signal.

``mlflow.tracing.export.genai_semconv`` is a banned import in shipped code and
legal here under ``[tool.ruff.lint.per-file-ignores] "tests/**" = ["SLF", "TID"]``.
That is OI-01's scope split: VER-08 bans private access in the *shipped package*,
and test code may use private APIs freely. **No third per-file-ignore was added
for this file** — plan 01-03 asserts the exemption count is exactly two.

**Every import that mentions MLflow lives inside a function body, and must stay
there.** ``tests/conftest.py`` lines 15-24 silences MLflow's outbound telemetry
from a session-scoped autouse fixture, and that fixture's own comment names the
condition it depends on: nothing imports MLflow at module scope. pytest imports
every test module during *collection*, and collection finishes before any
session-scoped fixture runs — so a module-scope import here would make an
outbound MLflow telemetry call on every run of the entire suite, before the
guard is in place, in a project whose PROJECT.md forbids network calls to any
hosted endpoint during development or testing. The SDK's own import moved down
with it for a second reason: the probe that enforces this rule matches the
substring ``mlflow``, and ``revenium_mlflow`` contains it. Do not "tidy" either
import back to the top of the file, and do not hide them behind a module-level
helper that runs its import at import time. This costs D-03 nothing — a module
MLflow has moved still raises ``ImportError`` from a function body, loudly, in
the test that needs it, naming the module.

The version lookup obeys the same rule from the other side:
``importlib.metadata.version`` reads *distribution metadata* and imports neither
package, so it is safe at module scope and is called at test time.

**Scope: cache tokens only, deliberately.** MLflow's translator emits finish
reasons through its OpenAI converter alone — ``extract_response_attrs`` is absent
from the Anthropic, Gemini and Bedrock converters — so an A/B on this Anthropic
fixture that expected parity on ``gen_ai.response.finish_reasons`` would show a
reason here and none there and look like an SDK bug. That is MLflow's behaviour,
not a defect in either mapper, and it is a different subject. Do not widen this
test into one.
"""

import importlib.metadata
from collections.abc import Mapping
from pathlib import Path

import pytest
from opentelemetry.util.types import AttributeValue

from tests.fixtures.spans import anthropic_cache_span

pytestmark = pytest.mark.unit

#: Resolved from this file rather than from the working directory, so the test
#: means the same thing run from anywhere. Pinned as a module constant for the
#: reason ``tests/unit/test_import_purity.py`` pins its own transcript: the
#: evidence file and the test that produces it stay tied together.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRANSCRIPT = _REPO_ROOT / "docs" / "verification" / "sem-05-cache-token-ab.md"

#: The exact command the committed transcript was captured from. Asserted to be
#: present in the file, so the transcript cannot claim a different provenance
#: from the one that actually produced it.
_COMMAND = ".venv/bin/python -m pytest tests/unit/test_semconv_cache_tokens.py -q -s"

#: The fixture's cache counts. Small and distinct from every other number on the
#: span, so a transcript line carrying them cannot have picked them up by chance.
_CACHE_READ = 3
_CACHE_CREATION = 2

_INPUT_TOKENS_KEY = "gen_ai.usage.input_tokens"
_OUTPUT_TOKENS_KEY = "gen_ai.usage.output_tokens"
_CACHE_READ_KEY = "gen_ai.usage.cache_read_input_tokens"
_CACHE_CREATION_KEY = "gen_ai.usage.cache_creation_input_tokens"

#: The two spellings the backend **also** recognizes and this SDK emits from
#: nowhere (D-02). The reason is arithmetic rather than taste: a backend that
#: sums duplicate numeric keys rather than deduping them would double the cached
#: portion — an overbill in the exact field that exists to prevent overbilling.
#: One spelling per count is the only shape that cannot be summed with itself.
_ALTERNATIVE_CACHE_SPELLINGS = (
    "gen_ai.usage.cache_read_tokens",
    "gen_ai.usage.cache_creation_tokens",
)

_USAGE_PREFIX = "gen_ai.usage."

#: The two line labels, padded so the dicts start at the same column and the
#: comparison is legible to a reader rather than merely machine-checkable. The
#: leading token of each is what the transcript gate greps for, so neither may
#: gain a prefix.
_REVENIUM_LABEL = "REVENIUM map_span               "
_MLFLOW_LABEL = "MLFLOW   translate_span_to_genai"


def _usage_line(label: str, attributes: Mapping[str, AttributeValue]) -> str:
    """One labelled line: a mapper's name and the usage attributes it emitted.

    Filtered to ``gen_ai.usage.*`` on both sides so the two lines differ only in
    the subject under comparison. Insertion order is preserved by both mappers,
    so the rendered dict is stable across runs — which is what lets the committed
    transcript be diffed byte-for-byte against a fresh capture.
    """
    usage = {key: value for key, value in attributes.items() if key.startswith(_USAGE_PREFIX)}
    return f"{label} usage attributes: {usage}"


def _versions_line() -> str:
    """The releases this run was made against, read from distribution metadata.

    ``importlib.metadata.version`` reads the installed distribution's metadata
    and imports neither package, so this stays inside the no-module-scope-MLflow
    rule the module docstring sets out.
    """
    mlflow_version = importlib.metadata.version("mlflow")
    otel_version = importlib.metadata.version("opentelemetry-sdk")
    return f"VERSIONS mlflow={mlflow_version} opentelemetry-sdk={otel_version}"


def _map_both() -> tuple[Mapping[str, AttributeValue], Mapping[str, AttributeValue]]:
    """One span object, mapped by this SDK and translated by MLflow's own code.

    The *same* ``ReadableSpan`` instance goes to both, so nothing about the
    difference below can be attributed to two fixtures having drifted apart.

    Both imports live here rather than at module scope, and the module docstring
    records why at length: pytest imports every test module during collection,
    before ``tests/conftest.py``'s session-scoped telemetry guard has run.
    """
    from mlflow.tracing.export.genai_semconv.translator import translate_span_to_genai

    from revenium_mlflow.tracing.semconv import map_span

    span = anthropic_cache_span(cache_read=_CACHE_READ, cache_creation=_CACHE_CREATION)
    return dict(map_span(span).attributes), dict(translate_span_to_genai(span).attributes or {})


def test_the_sdk_carries_the_cache_tokens_mlflows_own_translator_drops() -> None:
    """Criterion 2, whole, in one captured output.

    The printed pair is the evidence; the assertions below are what make the
    printed pair falsifiable. A leading blank line is emitted first because
    ``pytest -q -s`` writes its progress characters without a trailing newline,
    and a transcript line that began with a stray ``.`` would no longer be the
    line the capture gate greps for.
    """
    ours, theirs = _map_both()

    print()
    print(_versions_line())
    print(_usage_line(_REVENIUM_LABEL, ours))
    print(_usage_line(_MLFLOW_LABEL, theirs))

    # This SDK carries both cache counts, as exact integers. The type check is
    # exact rather than ``isinstance`` because ``isinstance(True, int)`` is True
    # and the OTLP encoder would ship such a value as ``bool_value`` (SEM-04).
    assert ours[_CACHE_READ_KEY] == _CACHE_READ
    assert type(ours[_CACHE_READ_KEY]) is int, "cache_read must be exactly int, not a bool"
    assert ours[_CACHE_CREATION_KEY] == _CACHE_CREATION
    assert type(ours[_CACHE_CREATION_KEY]) is int, "cache_creation must be exactly int, not a bool"

    # MLflow's translator carries no cache key at all — not a zero, not an
    # alternative spelling, nothing. This is the overbill, stated mechanically.
    assert [key for key in theirs if "cache" in key.lower()] == [], theirs

    # ...and the difference is isolated to the cache keys: both mappers agree on
    # the input and output counts. Without this a reader could not tell whether
    # the transcript shows a cache-token difference or two mappers disagreeing
    # about everything.
    assert ours[_INPUT_TOKENS_KEY] == theirs[_INPUT_TOKENS_KEY]
    assert ours[_OUTPUT_TOKENS_KEY] == theirs[_OUTPUT_TOKENS_KEY]

    # D-02: exactly one spelling per count, from either mapper.
    for spelling in _ALTERNATIVE_CACHE_SPELLINGS:
        assert spelling not in ours, f"{spelling} must be emitted by nothing"
        assert spelling not in theirs, f"{spelling} must be emitted by nothing"


def test_the_transcript_records_this_runs_side_by_side_output() -> None:
    """The committed evidence still says what this run just said.

    A transcript that has drifted from the behaviour it documents is worse than
    no transcript, because it is read as current. Re-deriving both lines here is
    what makes the file a capture rather than a composition — the shell gate in
    the plan diffs a fresh ``| tee`` capture against these same two lines, and a
    hand-typed file fails both.
    """
    ours, theirs = _map_both()

    assert _TRANSCRIPT.is_file(), f"{_TRANSCRIPT} is missing"
    transcript = _TRANSCRIPT.read_text(encoding="utf-8")

    for line in (_usage_line(_REVENIUM_LABEL, ours), _usage_line(_MLFLOW_LABEL, theirs)):
        assert line in transcript, f"transcript is missing {line!r}"


def test_the_transcript_records_the_command_it_was_captured_from() -> None:
    """Provenance, not decoration: the reader can re-run exactly this.

    The installed versions are recorded in the transcript too, but deliberately
    are **not** asserted here: they legitimately differ across VER-07's four
    matrix legs, and a test pinning them would turn "this claim is about MLflow
    3.16.0" into a false failure on the 3.15.0 leg.
    """
    assert _COMMAND in _TRANSCRIPT.read_text(encoding="utf-8")
