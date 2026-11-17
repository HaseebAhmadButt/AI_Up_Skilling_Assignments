# Repository Guidelines

## Project Structure & Module Organization

This repository contains two Python assignment stages. `L1/` holds three versions of an approval-routing agent, shared helpers, and its test cases. `L2/` contains the interactive approval workflow: `main.py` is the console entry point; `workflow/` implements submission, validation, routing, scheduling, and state; `tools/` contains agent-facing operations; `mock_data/` provides the employee, policy, and notification fixtures; and `tests/` contains the workflow and decision-matrix suites. `L2/DECISIONS.md` records important behavior and known limits. Keep new tests alongside the relevant stage and avoid committing credentials, virtual environments, bytecode, or generated artifacts.

## Build, Test, and Development Commands

There is no separate build step or dependency manifest in the repository. Use the project virtual environment if needed, then run commands from the relevant directory so the modules resolve correctly:

- `cd L2 && python main.py` starts the interactive workflow application.
- `cd L2 && python -m unittest discover -s tests -v` runs all L2 unit tests.
- `cd L2 && python -m unittest tests.test_matrix -v` runs the approval decision matrix.
- `cd L1 && python run_tests.py` runs all L1 agent suites; pass `v1.0.0`, `v1.0.1`, or `v2.0.0` to select versions.

L2 tests stub the agents and do not require an API key.

## Coding Style & Naming Conventions

Use four spaces for Python indentation, descriptive `snake_case` names for functions and variables, and `PascalCase` for classes. Keep workflow logic in the corresponding `L2/workflow/` module and mock fixtures in `L2/mock_data/`. Tests use `unittest`, are named `test_*.py`, and methods start with `test_`. No formatter or linter is configured; match the surrounding style and keep changes focused.

## Testing Guidelines

Add regression tests for behavior changes, especially approval thresholds, identity checks, routing, and workflow status. Run the relevant L2 suite after changes; use the complete discovery command for cross-module changes. L1 changes should be checked with the matching version suite, or all suites when shared helpers change. No coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent commits use short, plain summaries such as `Disapproval message validation added` and `L2 Assignment 2.0.0 completed.` Follow that concise style and describe the change. Pull requests should explain behavior and affected stage, list validation commands and results, link related work when applicable, and include console output or screenshots only when they clarify a user-visible change.

## Configuration & Data Safety

Keep API keys and other secrets in local environment files; never commit them. L2 uses in-memory workflow state and mock employee and policy data, so do not treat it as persistent or production data. Avoid committing logs unless they are intentional test fixtures.
