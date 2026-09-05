"""A deliberate control subject: a module that breaches the private-access wall.

This file exists to be *detected*. `tests/unit/test_private_access_wall.py`
asserts that the shipped package contains zero private MLflow and OpenTelemetry
accesses — an assertion a scanner that detects nothing at all would also satisfy.
Pointing the same scanner at this file, and requiring it to find exactly the two
breaches planted here, is what makes the clean result mean something.

Nothing in ``src/revenium_mlflow`` imports this module and nothing should. It is
not collected as a test — pytest only collects ``test_*.py`` — and it is read as
text by the scanner rather than imported.

The two breaches, one of each kind the scanner recognises:

1. An underscore-prefixed attribute read on an object reached from ``mlflow``.
   ``_active_span_processor`` is not invented for this fixture; it is the exact
   private OpenTelemetry state MLflow itself reaches into, and the state Phase 4
   will be tempted to read in order to detect processor eviction.
2. An import of an underscore-prefixed submodule of an OpenTelemetry package.
   ``opentelemetry.util._once`` is likewise real — the ``Once`` latch is what
   makes tracer-provider initialisation happen exactly once, and reading it is
   how you would detect that configuration arrived too late.

Both are plausible temptations rather than synthetic nonsense, which is the
point: the wall has to hold against the accesses someone would actually reach
for under deadline.
"""

import mlflow

# Imported for the scanner to find, never called. F401 is suppressed narrowly,
# on this one line, rather than by widening any rule's exemption list.
from opentelemetry.util._once import Once  # noqa: F401


def read_private_processor_state() -> object:
    """Read MLflow's private span-processor state. Never call this."""
    return mlflow.tracing._active_span_processor
