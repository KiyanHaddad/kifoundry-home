# Contributing

Read the product objective and contracts first. Name the user moment your change improves, reproduce the current gap, and keep the change within a coherent responsibility. Preserve histories and exact version semantics.

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
```

Optional development environment:

```sh
python -m venv .venv
python -m pip install -e ".[dev]"
python -m ruff check home tests scripts
python -m mypy home
```

Use the environment's Python after activation. CI installs the development extras and executes its configured checks; the existence of that workflow is not evidence that a GitHub run passed.

Tests should establish observable behavior: shared context, attribution, duplicate handling, cancellation, recovery and versions. Avoid tests that only restate implementation. Keep native provider smoke runs opt-in because they consume usage and require an account.

Do not commit local config, auth files, databases, histories, raw provider streams or private receipts. Report fixture results, genuine provider evidence, owner acceptance and publication separately.

For a pull request, explain the concrete problem, resulting behavior and checks run. Preserve unresolved limitations. Separate unrelated redesigns from the change being reviewed.
