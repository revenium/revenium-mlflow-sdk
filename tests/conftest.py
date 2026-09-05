"""pytest configuration root.

This file exists so pytest roots the test session at the repository root and
``tests`` imports resolve as a package. It deliberately defines no fixtures yet;
shared fixtures — the fake OTLP collector, the ``respx`` router, the socket
guard — arrive with the plans that need them.
"""
