"""Hand-labeled scenarios for regression testing.

Each ``.json`` file in this folder is a fixed-context snapshot of a real
historical moment plus the signal we expect the orchestrator to emit
for it. The CI test (``eval/tests/test_scenarios.py``) loads every file
and runs the full pipeline on it.

Adding a scenario? See ``scenarios/README.md`` for the schema and the
methodology used for the bundled set.
"""
