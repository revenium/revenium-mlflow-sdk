# SEM-05 — MLflow collects cache tokens; MLflow's own translator drops them

Captured evidence for Phase 02 Plan 05, criterion 2. The block in section 2 is verbatim stdout of
the command shown above it, extracted by redirection on this machine against the working tree at the
commit this file is committed in. Nothing below was re-typed, re-wrapped, or tidied.

**What this file has to prove.** This SDK exists because MLflow *collects* prompt-cache token counts
and its own OTLP translator discards them. `TokenUsageKey` declares `cache_read_input_tokens` and
`cache_creation_input_tokens` identically at the `3.15.0` floor and at `3.16.0`, and six integration
modules populate them; `_translate_universal_attributes` reads `input_tokens` and `output_tokens` out
of `mlflow.chat.tokenUsage` and nothing else (`translator.py:115-121`, identical at both versions).
So a prompt-caching customer's cached tokens never reach Revenium through MLflow's own export path,
and no error appears on either side — the span arrives, it is accepted, and the cheapest tokens in
the invoice are simply not there. Two green checkmarks in two files would not show a reader that.
One test feeding the *identical span object* to both mappers and printing both usage-attribute dicts
does.

**Scope and boundaries.**

- **No CI has run.** `.github/workflows/version-matrix.yml` is provision only and says so in its own
  header (plan 01-07). Everything below was produced by running the command shown, locally. Nothing
  here should be read as a CI result, a release, a publication, or a statement about production
  readiness.
- **This is evidence about the installed MLflow, and about nothing else.** It proves that MLflow
  `3.16.0`'s GenAI-semconv translator emits neither cache key for this span. It is **not** evidence
  about the Revenium backend — this project makes no call to Revenium, to a customer environment, or
  to any hosted endpoint — and it is not a claim about MLflow releases other than the one named in
  the `VERSIONS` line below.
- No command reads or prints an environment variable, and no credential is set or referenced. The
  output is two distribution versions and two attribute dicts of integer token counts.
- The one command here imports MLflow. `tests/conftest.py` disables MLflow's own outbound telemetry
  for the whole session before any test imports it, and every MLflow import in the test module lives
  inside a function body so that guard wins the race against pytest's collection pass.
- The command runs under `.venv/bin/python`, the same interpreter `scripts/check.sh` resolves as
  `PY`. The system `python3` on this machine is 3.9.6, below this project's 3.10 floor, so a bare
  PATH lookup would make this transcript unattributable.

**Environment.** macOS, arm64. Interpreter `Python 3.10.20` at `.venv/bin/python`. The MLflow and
OpenTelemetry SDK releases the claim is made against are in the captured `VERSIONS` line, read from
installed distribution metadata by the same run that produced the comparison — not typed here.

---

## 1. Why the capture is of the labelled lines, and not of the whole run

`tests/unit/test_semconv_cache_tokens.py` contains the A/B *and* two tests asserting that this file
still records what the A/B just printed. That is deliberate — it is what keeps the evidence and the
behaviour from drifting apart — and it makes the first capture necessarily red: the transcript does
not exist yet when the run that produces it happens. The same circularity is handled the same way in
`docs/verification/ver-08-plant-and-revert.md`, which captures each mechanism on its own isolated
run rather than weakening a gate to get everything into one transcript.

So the block below is the three labelled lines of the capture, spliced verbatim out of the redirected
output. The summary line of that first run is not included, because it reported the two
transcript-assertion failures that this file's existence resolves. Section 3 records the run made
after the file was written, where all three tests pass.

---

## 2. The side-by-side comparison

```console
### .venv/bin/python -m pytest tests/unit/test_semconv_cache_tokens.py -q -s
VERSIONS mlflow=3.16.0 opentelemetry-sdk=1.44.0
REVENIUM map_span                usage attributes: {'gen_ai.usage.input_tokens': 100, 'gen_ai.usage.output_tokens': 20, 'gen_ai.usage.cache_read_input_tokens': 3, 'gen_ai.usage.cache_creation_input_tokens': 2}
MLFLOW   translate_span_to_genai usage attributes: {'gen_ai.usage.input_tokens': 100, 'gen_ai.usage.output_tokens': 20}
```

**What this proves.** One `ReadableSpan` carrying `cache_read_input_tokens: 3` and
`cache_creation_input_tokens: 2` went to both mappers. This SDK's `map_span` emitted both counts as
integers under the backend-recognized `gen_ai.usage.cache_*_input_tokens` keys. MLflow's own
`translate_span_to_genai` emitted no key containing `cache` at all — not a zero, not an alternative
spelling, nothing.

The two lines also agree on `gen_ai.usage.input_tokens` (100) and `gen_ai.usage.output_tokens` (20).
That agreement is load-bearing: without it a reader could not tell whether this transcript shows a
cache-token difference or two unrelated mappers disagreeing about everything. The difference is
isolated to the cache keys, which is exactly what criterion 2 is about.

`input_tokens` is the total MLflow recorded with the cached portion **included** — MLflow normalizes
cache tokens in as a subset on the Anthropic and Bedrock paths
(`mlflow/anthropic/autolog.py:194-200`). Anything computing `input_tokens + cache_read_input_tokens`
double-counts the cached portion. This SDK emits what MLflow recorded and computes nothing.

**What this does not prove.**

- Nothing about the Revenium backend. No call was made to it. That the emitted spellings are the ones
  the backend recognizes is a source read recorded in `.planning/PROJECT.md`, not a runtime
  observation, and this project forbids making one.
- Nothing about MLflow releases other than the one in the `VERSIONS` line. The claim that
  `translator.py:115-121` is identical at the `3.15.0` floor is a source read recorded in
  `02-RESEARCH.md`; VER-07's four-leg version matrix is what exercises it, and this test is one of
  the two in the phase whose result could differ between MLflow versions at all.
- Nothing about finish reasons. MLflow emits `gen_ai.response.finish_reasons` through its OpenAI
  converter alone, so an A/B on this Anthropic fixture would show a reason here and none there. That
  is MLflow's behaviour rather than a defect in either mapper, and the test is deliberately not
  widened into it.

---

## 3. The run after this file was written

```console
### .venv/bin/python -m pytest tests/unit/test_semconv_cache_tokens.py -q; echo "exit status: $?"
...                                                                      [100%]
3 passed in 0.85s
exit status: 0
```

**What this proves.** With the transcript in place, all three tests pass: the comparison itself, and
the two assertions that this file still records the comparison's two labelled lines and the command
they were captured from. The elapsed time in the summary line varies run to run and is not asserted
anywhere.

This run deliberately omits `-s`, so pytest captures the two labelled lines instead of printing them.
Including them a second time would put four labelled lines in this file, and the plan's gates count on
finding exactly one of each — a transcript that quietly doubled its own evidence is precisely the kind
of drift those gates exist to catch.

---

## Notes

- The `REVENIUM` and `MLFLOW` line prefixes are load-bearing rather than decorative. The plan's
  verification gate re-runs the test through `| tee`, greps both lines out of the fresh capture and
  out of this file, and requires them to be byte-identical. A hand-composed or hand-adjusted
  transcript fails that diff, which is the point — the earlier form of the gate counted line
  prefixes, and a hand-typed file with two correctly-prefixed lines satisfied it exactly as well as a
  captured one did.
- The installed versions in the `VERSIONS` line are deliberately **not** asserted by any test. They
  legitimately differ across VER-07's four matrix legs, and a test pinning them would turn "this
  claim is about MLflow 3.16.0" into a false failure on the 3.15.0 leg.
- `ruff format` also checks Python code blocks inside Markdown. Every block here is fenced `console`,
  not `python`, so none of the captured output is subject to reformatting.
- The MLflow module this test imports, `mlflow.tracing.export.genai_semconv.translator`, is a banned
  import in shipped code. It is legal in `tests/**` under the existing per-file-ignore — OI-01's
  scope split, where VER-08 bans private access in the shipped package and test code may use private
  APIs freely. No third exemption was added; the count in `pyproject.toml` is still exactly two.
