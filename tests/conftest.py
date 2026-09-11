"""Pytest configuration and fixtures.

Guard against no-op tests (those that can pass without actually testing anything).
A test with only `pass`, only a docstring, or empty body is a silent guardrail
failure waiting to happen.
"""

import ast
from pathlib import Path

import pytest


def pytest_configure(config):
    """Validate that no test is a no-op before running the suite."""
    # Scan all test files for empty/no-op tests
    test_dir = Path(__file__).resolve().parent
    issues = []

    for test_file in sorted(test_dir.glob("test_*.py")):
        with open(test_file) as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue

            # Skip: has a skip/xfail decorator (those are intentional)
            decorators = {
                d.id
                if isinstance(d, ast.Name)
                else d.func.id
                if isinstance(d, ast.Attribute) and isinstance(d.func, ast.Name)
                else None
                for d in node.decorator_list
            }
            if decorators & {"skip", "skipif", "xfail"}:
                continue  # Intentionally skipped tests are allowed

            body = node.body
            # Skip past docstring if present
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, (ast.Constant, ast.Str))
            ):
                body = body[1:]

            # Empty body after docstring: no-op
            if not body:
                issues.append(f"{test_file.name}::{node.name} (empty body)")
                continue

            # Only a pass statement: no-op
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                issues.append(f"{test_file.name}::{node.name} (only 'pass')")
                continue

    if issues:
        pytest.fail(
            "No-op tests detected (can pass without testing anything):\n  "
            + "\n  ".join(issues)
            + "\n\nEach test must do actual work: make an assertion, use pytest.raises,"
            " or call an assertion method like template.has_resource()."
        )
