"""Machinery for the PKG-09 import-purity probe.

Neither module here is imported by the test session. ``sitecustomize`` is
imported by CPython's ``site`` module at start-up in a *separate* interpreter,
and ``check_import`` is that interpreter's entry point. Both are deliberately
kept out of the pytest process: a socket guard installed in-process would stay
installed for the rest of the session and change the behaviour of every other
test.

The package marker exists so the directory is a package like every other
directory under ``tests/``, and so a future helper here can be imported by path
without the tree acquiring an implicit-namespace-package exception.
"""
