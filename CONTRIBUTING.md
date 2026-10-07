# Contributing

Read the [product objective](docs/PRODUCT.txt), [architecture](docs/ARCHITECTURE.md) and [contracts](docs/CONTRACTS.md). Name the user moment your change improves, reproduce the gap, and keep the change within a coherent responsibility. Preserve histories and exact version semantics.

## Set up a development environment

Use Python 3.11+ and Git. Node.js is needed only for the browser-module syntax checks. From the source folder, create an environment and install the development extras:

```sh
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

On macOS/Linux:

```sh
.venv/bin/python -m pip install -e ".[dev]"
```

In the commands below, replace `python` with that environment's Python path. Activation is optional.

## Check a change

From the repository root:

```sh
python -m unittest discover -s tests -v
python -m compileall -q home scripts
node --check home/web/app.js
node --check home/web/world.js
node --check home/web/world-layout.js
node --check home/web/resident-directory.js
node --check home/web/room.js
python scripts/check_public_tree.py
python scripts/check_public_tree.py --tracked
python scripts/check_public_tree.py --history
node --check home/web/http.js
python -m ruff check home tests scripts
python -m mypy home
```

CI runs on Ubuntu and Windows with Python 3.11 and 3.13. Default privacy scanning checks working files, including new docs; `--tracked` reads actual committed HEAD blobs, and `--history` reads reachable commit trees/metadata from a complete checkout. Neither substitutes for reviewing the pending index. Retain old reviewed asset hashes when replacing a binary so history remains inspectable.

Tests should establish observable behavior: shared context, attribution, duplicate handling, cancellation, recovery and versions. Avoid tests that only restate implementation. Keep native provider smoke runs opt-in because they consume usage and require an account.

## Before a public commit

Do not commit local config, auth files, databases, histories, raw provider streams or private receipts. After staging the intended files:

```sh
git diff --cached --stat
python scripts/check_public_tree.py --staged
```

The staged scan reads the actual index, so replacing a secret in the working copy cannot hide a still-staged value. Sensitive filenames are rejected even when force-added. New or changed binaries require explicit provenance and reviewed hashes in the scanner. Review prose, screenshots, commit metadata and history manually too.

Report fixture results, genuine provider evidence, user acceptance and publication separately. Native smoke runs consume usage; ordinary CI must not launch them.

For a pull request, explain the concrete problem, resulting behavior and checks run. Preserve unresolved limitations. Separate unrelated redesigns from the change being reviewed.
