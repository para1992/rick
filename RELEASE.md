# Release Checklist

Use this checklist before tagging or publishing Rick.

## Preflight

```bash
git status --short
git diff --check
python3 -m pip install -r requirements.lock -e .
python3 -m pytest
python3 -m compileall -q seedflow_cli tests
python3 -m seedflow_cli --help
```

## Smoke Test

Run without an API key to verify the local mock path:

```bash
OPENROUTER_API_KEY= python3 -m seedflow_cli 'RESOLVE("Release smoke","Must complete locally")>GEN(plan,1)>JUDGE' --mode LOG_STEP --run-dir runs/release-smoke --max-calls 5
```

Run with an API key before a public release:

```bash
python3 -m seedflow_cli 'RESOLVE("Write a short release note","Must be specific and useful")>GEN(plan,3)>JUDGE>GEN(draft,3)>JUDGE>EDIT(strict)' --mode LOG_STEP --run-dir runs/release-real-llm --max-calls 10
```

## Package Check

Build a wheel and install it in a clean virtual environment:

```bash
python3 -m pip wheel --no-deps . -w /tmp/rick-release-wheel
python3 -m venv /tmp/rick-release-venv
/tmp/rick-release-venv/bin/python -m pip install /tmp/rick-release-wheel/rick-0.1.0-py3-none-any.whl
/tmp/rick-release-venv/bin/rick --help
OPENROUTER_API_KEY= /tmp/rick-release-venv/bin/rick 'RESOLVE("Installed wheel smoke","Must complete locally")>GEN(plan,1)>JUDGE' --mode LOG_STEP --run-dir /tmp/rick-installed-wheel-smoke --max-calls 5
/tmp/rick-release-venv/bin/python -m pip check
```

## Git Hygiene

Before the first commit:

- Stage source files, tests, README, docs, `requirements.lock`, and release docs.
- Confirm deletions of generated artifacts such as `*.egg-info/` and `tmp-check/`.
- Confirm whether removed sample/context files should stay removed.
- Do not stage local run output under `runs/`.
- Do not stage `.env` or other secrets.

## Known First-Release Decisions

- Pick and document a license before publishing outside the local project.
- Decide whether `docs/DEMO.md`, `docs/record-demo.sh`, and `docs/rick-demo.tape` are release docs or local-only assets.
