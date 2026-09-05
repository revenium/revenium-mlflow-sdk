"""Control subjects for tests that need a known-dirty input.

Nothing in ``src/revenium_mlflow`` imports this package, and nothing in it is
importable machinery for the SDK. It exists so that tests which claim to detect
something can be pointed at a subject that definitely contains it.
"""
