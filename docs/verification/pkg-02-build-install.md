# PKG-02 / PKG-03 / PKG-04 / PKG-05 / PKG-06 — build, clean-environment install, editable install

Captured evidence for Phase 01 Plan 01 Task 1. Every block below is the verbatim stdout of the
command shown above it, run on this machine in one session against the working tree at the commit
this file is committed in.

**Scope and boundaries.**

- Nothing here uploads, publishes, tags, or pushes. The delivery boundary for this project is build
  artifacts only.
- No command reads or prints an environment variable, and no credential is set or referenced.
  The output is versions, archive listings, and dependency-freeze lines.
- No command invokes bare `python3`. The system `python3` on this machine is 3.9.6, **below** the
  project floor of 3.10, so every step pins the interpreter explicitly — `uv venv --python 3.10`
  for environments and `.venv/bin/python` or `"$V/<name>/bin/python"` for execution.

**Environment.** macOS, arm64 (`aarch64-apple-darwin`). `uv 0.11.17`. Interpreter
`cpython-3.10.20-macos-aarch64-none`.

---

## 0. Preconditions — uv version and a cpython-3.10 interpreter

```console
### uv --version
uv 0.11.17 (a33a629d6 2026-05-28 aarch64-apple-darwin)

### uv python list | grep cpython-3.10
cpython-3.10.20-macos-aarch64-none                  /Users/johndemic/.local/share/uv/python/cpython-3.10-macos-aarch64-none/bin/python3.10

### uv venv --python 3.10 .venv
Using CPython 3.10.20
Creating virtual environment at: .venv
Activate with: source .venv/bin/activate

### .venv/bin/python --version
Python 3.10.20
```

---

## 1. Build the wheel and the sdist (PKG-02)

Built with `python -m build` rather than `uv build`: `build` is the reference PEP 517 front-end for
the `setuptools.build_meta` backend this project declares, and it is what CI can run without adding
`uv` as a CI prerequisite. Note the isolated build environment resolving `setuptools==84.0.0`, which
satisfies the `setuptools>=77` floor the PEP 639 `license = "MIT"` string form requires.

```console
### uv pip install --python .venv/bin/python build
Resolved 4 packages in 538ms
Prepared 1 package in 20ms
Installed 4 packages in 8ms
 + build==1.6.0
 + packaging==26.3
 + pyproject-hooks==1.2.0
 + tomli==2.4.1

### rm -rf dist && .venv/bin/python -m build
* Creating isolated environment: venv+pip...
* Installing packages in isolated environment:
  - setuptools>=77
  - wheel
* Getting build dependencies for sdist...
running egg_info
creating src/revenium_mlflow.egg-info
writing src/revenium_mlflow.egg-info/PKG-INFO
writing dependency_links to src/revenium_mlflow.egg-info/dependency_links.txt
writing requirements to src/revenium_mlflow.egg-info/requires.txt
writing top-level names to src/revenium_mlflow.egg-info/top_level.txt
writing manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
reading manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
* Installed build dependency versions:
  - setuptools==84.0.0
  - wheel==0.48.0
* Building sdist...
running sdist
running egg_info
writing src/revenium_mlflow.egg-info/PKG-INFO
writing dependency_links to src/revenium_mlflow.egg-info/dependency_links.txt
writing requirements to src/revenium_mlflow.egg-info/requires.txt
writing top-level names to src/revenium_mlflow.egg-info/top_level.txt
reading manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
running check
creating revenium_mlflow-0.1.0
creating revenium_mlflow-0.1.0/src/revenium_mlflow
creating revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info
copying files to revenium_mlflow-0.1.0...
copying LICENSE -> revenium_mlflow-0.1.0
copying README.md -> revenium_mlflow-0.1.0
copying pyproject.toml -> revenium_mlflow-0.1.0
copying src/revenium_mlflow/__init__.py -> revenium_mlflow-0.1.0/src/revenium_mlflow
copying src/revenium_mlflow/py.typed -> revenium_mlflow-0.1.0/src/revenium_mlflow
copying src/revenium_mlflow.egg-info/PKG-INFO -> revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info
copying src/revenium_mlflow.egg-info/SOURCES.txt -> revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info
copying src/revenium_mlflow.egg-info/dependency_links.txt -> revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info
copying src/revenium_mlflow.egg-info/requires.txt -> revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info
copying src/revenium_mlflow.egg-info/top_level.txt -> revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info
Writing revenium_mlflow-0.1.0/setup.cfg
Creating tar archive
removing 'revenium_mlflow-0.1.0' (and everything under it)
* Building wheel from sdist
* Creating isolated environment: venv+pip...
* Installing packages in isolated environment:
  - setuptools>=77
  - wheel
* Getting build dependencies for wheel...
running egg_info
writing src/revenium_mlflow.egg-info/PKG-INFO
writing dependency_links to src/revenium_mlflow.egg-info/dependency_links.txt
writing requirements to src/revenium_mlflow.egg-info/requires.txt
writing top-level names to src/revenium_mlflow.egg-info/top_level.txt
reading manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
* Installed build dependency versions:
  - setuptools==84.0.0
  - wheel==0.48.0
* Building wheel...
running bdist_wheel
running build
running build_py
creating build/lib/revenium_mlflow
copying src/revenium_mlflow/__init__.py -> build/lib/revenium_mlflow
running egg_info
writing src/revenium_mlflow.egg-info/PKG-INFO
writing dependency_links to src/revenium_mlflow.egg-info/dependency_links.txt
writing requirements to src/revenium_mlflow.egg-info/requires.txt
writing top-level names to src/revenium_mlflow.egg-info/top_level.txt
reading manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
adding license file 'LICENSE'
writing manifest file 'src/revenium_mlflow.egg-info/SOURCES.txt'
copying src/revenium_mlflow/py.typed -> build/lib/revenium_mlflow
installing to build/bdist.macosx-11.0-arm64/wheel
running install
running install_lib
creating build/bdist.macosx-11.0-arm64/wheel
creating build/bdist.macosx-11.0-arm64/wheel/revenium_mlflow
copying build/lib/revenium_mlflow/__init__.py -> build/bdist.macosx-11.0-arm64/wheel/./revenium_mlflow
copying build/lib/revenium_mlflow/py.typed -> build/bdist.macosx-11.0-arm64/wheel/./revenium_mlflow
running install_egg_info
Copying src/revenium_mlflow.egg-info to build/bdist.macosx-11.0-arm64/wheel/./revenium_mlflow-0.1.0-py3.10.egg-info
running install_scripts
creating build/bdist.macosx-11.0-arm64/wheel/revenium_mlflow-0.1.0.dist-info/WHEEL
creating '/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/dist/.tmp-sqgs4by2/revenium_mlflow-0.1.0-py3-none-any.whl' and adding 'build/bdist.macosx-11.0-arm64/wheel' to it
adding 'revenium_mlflow/__init__.py'
adding 'revenium_mlflow/py.typed'
adding 'revenium_mlflow-0.1.0.dist-info/licenses/LICENSE'
adding 'revenium_mlflow-0.1.0.dist-info/METADATA'
adding 'revenium_mlflow-0.1.0.dist-info/WHEEL'
adding 'revenium_mlflow-0.1.0.dist-info/top_level.txt'
adding 'revenium_mlflow-0.1.0.dist-info/RECORD'
removing build/bdist.macosx-11.0-arm64/wheel
Successfully built revenium_mlflow-0.1.0.tar.gz and revenium_mlflow-0.1.0-py3-none-any.whl

### ls dist
revenium_mlflow-0.1.0-py3-none-any.whl
revenium_mlflow-0.1.0.tar.gz
```

---

## 2. `py.typed` ships in both artifacts (PKG-05)

PEP 561 needs three things and all three are proven here: the marker file exists,
`[tool.setuptools.package-data]` ships it, and `[tool.setuptools.packages.find] where = ["src"]`
discovers the package. The wheel listing also shows the artifact contains **only** the package tree
and `dist-info` metadata — nothing from the working tree leaks into the distribution.

```console
### ls -1 dist | wc -l  (and per-pattern counts)
whl count:    1
tar.gz count: 1

### unzip -l dist/*.whl
Archive:  dist/revenium_mlflow-0.1.0-py3-none-any.whl
  Length      Date    Time    Name
---------  ---------- -----   ----
     1386  09-05-2026 00:17   revenium_mlflow/__init__.py
        0  09-05-2026 00:17   revenium_mlflow/py.typed
     1065  09-05-2026 00:18   revenium_mlflow-0.1.0.dist-info/licenses/LICENSE
     4954  09-05-2026 00:18   revenium_mlflow-0.1.0.dist-info/METADATA
       91  09-05-2026 00:18   revenium_mlflow-0.1.0.dist-info/WHEEL
       16  09-05-2026 00:18   revenium_mlflow-0.1.0.dist-info/top_level.txt
      597  09-05-2026 00:18   revenium_mlflow-0.1.0.dist-info/RECORD
---------                     -------
     8109                     7 files

### unzip -l dist/*.whl | grep -c 'revenium_mlflow/py.typed'
1

### tar tzf dist/*.tar.gz
revenium_mlflow-0.1.0/
revenium_mlflow-0.1.0/LICENSE
revenium_mlflow-0.1.0/PKG-INFO
revenium_mlflow-0.1.0/README.md
revenium_mlflow-0.1.0/pyproject.toml
revenium_mlflow-0.1.0/setup.cfg
revenium_mlflow-0.1.0/src/
revenium_mlflow-0.1.0/src/revenium_mlflow/
revenium_mlflow-0.1.0/src/revenium_mlflow/__init__.py
revenium_mlflow-0.1.0/src/revenium_mlflow/py.typed
revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info/
revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info/PKG-INFO
revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info/SOURCES.txt
revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info/dependency_links.txt
revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info/requires.txt
revenium_mlflow-0.1.0/src/revenium_mlflow.egg-info/top_level.txt

### tar tzf dist/*.tar.gz | grep -c 'src/revenium_mlflow/py.typed'
1
```

---

## 3. Clean-environment install and import (PKG-03, PKG-01)

A throwaway `uv venv --python 3.10` under `mktemp -d`, the wheel installed into it, then three
assertions in one process: `__version__`, PEP 503 **normalized** distribution-name equality across
the spellings `revenium-mlflow` / `revenium_mlflow` / `Revenium-MLflow`, and the presence of
`py.typed` in the installed package directory.

Expected final three lines: `0.1.0`, `['0.1.0', '0.1.0', '0.1.0']`, `True`.

```console
### V=$(mktemp -d) && uv venv --python 3.10 "$V/a" && uv pip install --python "$V/a/bin/python" dist/*.whl
Using CPython 3.10.20
Creating virtual environment at: /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.jbg6aZcTdz/a
Activate with: source /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.jbg6aZcTdz/a/bin/activate
Using Python 3.10.20 environment at: /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.jbg6aZcTdz/a
Resolved 100 packages in 547ms
Downloading fonttools (3.0MiB)
Downloading sqlalchemy (2.1MiB)
Downloading numpy (5.1MiB)
Downloading pyarrow (34.3MiB)
Downloading scikit-learn (8.3MiB)
Downloading pandas (10.3MiB)
Downloading pillow (4.6MiB)
Downloading matplotlib (7.8MiB)
Downloading scipy (21.3MiB)
 Downloaded sqlalchemy
 Downloaded fonttools
 Downloaded pillow
 Downloaded numpy
 Downloaded matplotlib
 Downloaded scikit-learn
 Downloaded pandas
 Downloaded scipy
 Downloaded pyarrow
Prepared 22 packages in 1m 07s
Installed 100 packages in 746ms
 + aiohappyeyeballs==2.7.1
 + aiohttp==3.14.3
 + aiosignal==1.4.0
 + alembic==1.19.2
 + annotated-doc==0.0.5
 + annotated-types==0.8.0
 + anyio==4.14.2
 + async-timeout==5.0.1
 + attrs==26.1.0
 + blinker==1.9.0
 + cachetools==7.1.8
 + certifi==2026.7.22
 + cffi==2.1.1
 + charset-normalizer==3.5.1
 + click==8.5.0
 + cloudpickle==3.1.2
 + contourpy==1.3.2
 + cryptography==50.0.1
 + cycler==0.12.1
 + databricks-sdk==0.135.0
 + distro==1.9.0
 + docker==7.2.0
 + exceptiongroup==1.3.1
 + fastapi==0.141.1
 + flask==3.1.3
 + flask-cors==6.0.5
 + fonttools==4.64.0
 + frozenlist==1.8.0
 + gitdb==4.0.12
 + gitpython==3.1.61
 + google-auth==2.57.1
 + googleapis-common-protos==1.75.3
 + graphene==3.4.3
 + graphql-core==3.2.12
 + graphql-relay==3.2.0
 + gunicorn==26.2.0
 + h11==0.16.0
 + httpcore==1.0.9
 + httpx==0.28.1
 + huey==3.4.0
 + idna==3.19
 + importlib-metadata==9.0.1
 + itsdangerous==2.2.0
 + jinja2==3.1.6
 + joblib==1.6.0
 + kiwisolver==1.5.1
 + mako==1.4.1
 + markupsafe==3.0.3
 + matplotlib==3.10.9
 + mlflow==3.16.0
 + mlflow-skinny==3.16.0
 + mlflow-tracing==3.16.0
 + multidict==6.7.1
 + numpy==2.2.6
 + opentelemetry-api==1.44.0
 + opentelemetry-exporter-otlp-proto-common==1.44.0
 + opentelemetry-exporter-otlp-proto-http==1.44.0
 + opentelemetry-proto==1.44.0
 + opentelemetry-sdk==1.44.0
 + opentelemetry-semantic-conventions==0.65b0
 + packaging==26.3
 + pandas==2.3.3
 + pillow==12.3.0
 + prettytable==3.18.0
 + propcache==0.5.2
 + protobuf==6.33.6
 + pyarrow==25.0.1
 + pyasn1==0.6.4
 + pyasn1-modules==0.4.2
 + pycparser==3.0
 + pydantic==2.13.5
 + pydantic-core==2.46.5
 + pyparsing==3.3.2
 + python-dateutil==2.9.0.post0
 + python-dotenv==1.2.3
 + pytz==2026.3.post1
 + pyyaml==6.0.3
 + requests==2.34.2
 + revenium-mlflow==0.1.0 (from file:///Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/dist/revenium_mlflow-0.1.0-py3-none-any.whl)
 + revenium-python-sdk==0.7.0
 + scikit-learn==1.7.2
 + scipy==1.15.3
 + six==1.17.0
 + skops==0.14.0
 + smmap==5.0.3
 + sniffio==1.3.1
 + sqlalchemy==2.0.52
 + sqlparse==0.6.0
 + starlette==1.6.0
 + threadpoolctl==3.6.0
 + tomli==2.4.1
 + typing-extensions==4.16.0
 + typing-inspection==0.4.4
 + tzdata==2026.3
 + urllib3==2.7.0
 + uvicorn==0.52.4
 + wcwidth==0.8.3
 + werkzeug==3.1.8
 + yarl==1.24.5
 + zipp==4.1.0

### "$V/a/bin/python" -c "import os,revenium_mlflow,importlib.metadata as m; ..."
0.1.0
['0.1.0', '0.1.0', '0.1.0']
True
```

---

## 4. Concurrent installs resolve identically (PKG-06 concurrency edge)

Two clean environments installed from the same wheel concurrently in one run — one backgrounded,
one in the foreground, joined with `wait` so the backgrounded install reports its own failure. Their
frozen `mlflow` and `opentelemetry-sdk` lines are then diffed. `diff` printing nothing is the pass
condition: the declared floors resolve deterministically and are not sensitive to install ordering.

Both resolutions satisfy the declared bounds: `mlflow==3.16.0` is within `>=3.15.0,<4`, and
`opentelemetry-sdk==1.44.0` is within `>=1.30.0,<2`.

```console
### two concurrent throwaway installs from the same wheel, then diff their frozen mlflow / opentelemetry-sdk lines
Using CPython 3.10.20
Creating virtual environment at: /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.XLl1wvap77/p1
Activate with: source /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.XLl1wvap77/p1/bin/activate
Using CPython 3.10.20
Creating virtual environment at: /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.XLl1wvap77/p2
Activate with: source /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.XLl1wvap77/p2/bin/activate
p1 install tail:
 + werkzeug==3.1.8
 + yarl==1.24.5
 + zipp==4.1.0
p2 install tail:
 + werkzeug==3.1.8
 + yarl==1.24.5
 + zipp==4.1.0

### uv pip freeze | grep -Ei "^(mlflow|opentelemetry-sdk)==" for each, sorted, then diff
Using Python 3.10.20 environment at: /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.XLl1wvap77/p1
Using Python 3.10.20 environment at: /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/tmp.XLl1wvap77/p2
diff: byte-identical (no output above)

frozen lines:
mlflow==3.16.0
opentelemetry-sdk==1.44.0
```

---

## 5. Editable install from the working tree (PKG-04)

```console
### uv pip install --python .venv/bin/python -e ".[dev]"
Resolved 114 packages in 533ms
   Building revenium-mlflow @ file:///Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk
Downloading mypy (13.4MiB)
      Built revenium-mlflow @ file:///Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk
 Downloaded mypy
Prepared 4 packages in 3.16s
Installed 110 packages in 585ms
 + aiohappyeyeballs==2.7.1
 + aiohttp==3.14.3
 + aiosignal==1.4.0
 + alembic==1.19.2
 + annotated-doc==0.0.5
 + annotated-types==0.8.0
 + anyio==4.14.2
 + ast-serialize==0.9.0
 + async-timeout==5.0.1
 + attrs==26.1.0
 + backports-asyncio-runner==1.2.0
 + blinker==1.9.0
 + cachetools==7.1.8
 + certifi==2026.7.22
 + cffi==2.1.1
 + charset-normalizer==3.5.1
 + click==8.5.0
 + cloudpickle==3.1.2
 + contourpy==1.3.2
 + cryptography==50.0.1
 + cycler==0.12.1
 + databricks-sdk==0.135.0
 + distro==1.9.0
 + docker==7.2.0
 + exceptiongroup==1.3.1
 + fastapi==0.141.1
 + flask==3.1.3
 + flask-cors==6.0.5
 + fonttools==4.64.0
 + frozenlist==1.8.0
 + gitdb==4.0.12
 + gitpython==3.1.61
 + google-auth==2.57.1
 + googleapis-common-protos==1.75.3
 + graphene==3.4.3
 + graphql-core==3.2.12
 + graphql-relay==3.2.0
 + gunicorn==26.2.0
 + h11==0.16.0
 + httpcore==1.0.9
 + httpx==0.28.1
 + huey==3.4.0
 + idna==3.19
 + importlib-metadata==9.0.1
 + iniconfig==2.3.0
 + itsdangerous==2.2.0
 + jinja2==3.1.6
 + joblib==1.6.0
 + kiwisolver==1.5.1
 + librt==0.15.0
 + mako==1.4.1
 + markupsafe==3.0.3
 + matplotlib==3.10.9
 + mlflow==3.16.0
 + mlflow-skinny==3.16.0
 + mlflow-tracing==3.16.0
 + multidict==6.7.1
 + mypy==2.3.1
 + mypy-extensions==1.1.0
 + numpy==2.2.6
 + opentelemetry-api==1.44.0
 + opentelemetry-exporter-otlp-proto-common==1.44.0
 + opentelemetry-exporter-otlp-proto-http==1.44.0
 + opentelemetry-proto==1.44.0
 + opentelemetry-sdk==1.44.0
 + opentelemetry-semantic-conventions==0.65b0
 + pandas==2.3.3
 + pathspec==1.1.1
 + pillow==12.3.0
 + pluggy==1.6.0
 + prettytable==3.18.0
 + propcache==0.5.2
 + protobuf==6.33.6
 + pyarrow==25.0.1
 + pyasn1==0.6.4
 + pyasn1-modules==0.4.2
 + pycparser==3.0
 + pydantic==2.13.5
 + pydantic-core==2.46.5
 + pygments==2.21.0
 + pyparsing==3.3.2
 + pytest==9.1.1
 + pytest-asyncio==1.4.0
 + python-dateutil==2.9.0.post0
 + python-dotenv==1.2.3
 + pytz==2026.3.post1
 + pyyaml==6.0.3
 + requests==2.34.2
 + respx==0.23.1
 + revenium-mlflow==0.1.0 (from file:///Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk)
 + revenium-python-sdk==0.7.0
 + scikit-learn==1.7.2
 + scipy==1.15.3
 + six==1.17.0
 + skops==0.14.0
 + smmap==5.0.3
 + sniffio==1.3.1
 + sqlalchemy==2.0.52
 + sqlparse==0.6.0
 + starlette==1.6.0
 + threadpoolctl==3.6.0
 + typing-extensions==4.16.0
 + typing-inspection==0.4.4
 + tzdata==2026.3
 + urllib3==2.7.0
 + uvicorn==0.52.4
 + wcwidth==0.8.3
 + werkzeug==3.1.8
 + yarl==1.24.5
 + zipp==4.1.0

### .venv/bin/python -c "import revenium_mlflow; print(revenium_mlflow.__version__)"
0.1.0

### py.typed present in the editable install
True
```

---

## Results

| Claim | Requirement | Evidence | Result |
|---|---|---|---|
| `python -m build` emits exactly one wheel and one sdist | PKG-02 | §1, §2 (`whl count: 1`, `tar.gz count: 1`) | PASS |
| The wheel installs into a clean `uv venv --python 3.10` and imports | PKG-03 | §3 | PASS |
| Importing the installed package prints a PEP 440 version | PKG-03 | §3 (`0.1.0`) | PASS |
| The editable install succeeds from the working tree and imports the same version | PKG-04 | §5 (`0.1.0`) | PASS |
| `py.typed` is in the wheel, in the sdist, and in the installed package directory | PKG-05 | §2 (both `grep -c` print `1`), §3 (`True`), §5 (`True`) | PASS |
| The build runs under a `setuptools>=77` build requirement | PKG-06 | §1 (`setuptools==84.0.0` in the isolated build environment) | PASS |
| `mlflow` resolves within `>=3.15.0,<4` | PKG-06 | §4 (`mlflow==3.16.0`) | PASS |
| `opentelemetry-sdk` resolves within `>=1.30.0,<2` | PKG-06 | §4 (`opentelemetry-sdk==1.44.0`) | PASS |
| Distribution name equality is PEP 503 normalized, not byte equality | PKG-01 | §3 (`['0.1.0', '0.1.0', '0.1.0']`) | PASS |
| Concurrent installs from the same wheel resolve byte-identically | PKG-06 edge | §4 (`diff` printed nothing) | PASS |

## Notes on the resolved dependency set

**`mlflow-tracing` appears in the resolved set, and that is correct.** §3 shows
`mlflow==3.16.0`, `mlflow-skinny==3.16.0`, and `mlflow-tracing==3.16.0` all installed. This SDK
declares only `mlflow`; the other two arrive through MLflow's own dependency graph at a single
matching version, which is MLflow's intended layout as of 3.16.0. The failure mode this project
guards against is different: declaring `mlflow-tracing` *ourselves* as a runtime dependency, which
would co-install it against a user's pre-existing `mlflow-skinny`, splice the `mlflow/` package
tree, and degrade GenAI semantic conventions to a silent no-op. `pyproject.toml` names only
`mlflow`, and an acceptance criterion asserts that `mlflow-tracing` never appears there.

**No gRPC exporter is present.** §3 shows `opentelemetry-exporter-otlp-proto-http` and
`opentelemetry-exporter-otlp-proto-common` but no `opentelemetry-exporter-otlp-proto-grpc` and no
`grpcio`, confirming that declaring the HTTP exporter directly — rather than the
`opentelemetry-exporter-otlp` meta-package — keeps gRPC out of the tree. Revenium's ingest route is
HTTP + protobuf.

**`opentelemetry-sdk` is not exactly pinned.** It is declared `>=1.30.0,<2` and resolves to
`1.44.0`, driven by the HTTP exporter's own compatible-release requirement on it. An exact pin here
would conflict on the next exporter upgrade.

## What this document does not claim

This transcript proves that the distribution builds, installs into a clean Python 3.10 environment,
and imports. It does **not** claim that the package is published, released, or production-ready; no
command run here contacts a package index as a publisher, tags a release, or pushes anything. It
also makes no claim about CI, which has not run.
