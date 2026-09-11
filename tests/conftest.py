"""Pytest configuration and fixtures.

Guard against no-op tests (those that can pass without actually testing anything).
A test with only `pass`, only a docstring, or empty body is a silent guardrail
failure waiting to happen. Also catch tests with bodies but no assertions.
"""

import ast
from pathlib import Path

import pytest


def _has_assertion(node):
    """Check if a function node contains an assert statement, pytest.raises, or
    an assertion method call (template.has_resource, etc.).
    """
    for child in ast.walk(node):
        # Direct assert statement
        if isinstance(child, ast.Assert):
            return True
        # pytest.raises call or context manager
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if (
                child.func.attr == "raises"
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "pytest"
            ):
                return True
            # Assertion methods (template.has_resource, etc.)
            if any(
                child.func.attr.startswith(pattern)
                for pattern in ["has_", "assert_", "resource_count"]
            ):
                return True
        # pytest.raises as context manager (with statement)
        if (
            isinstance(child, ast.withitem)
            and isinstance(child.context_expr, ast.Call)
            and isinstance(child.context_expr.func, ast.Attribute)
            and child.context_expr.func.attr == "raises"
            and isinstance(child.context_expr.func.value, ast.Name)
            and child.context_expr.func.value.id == "pytest"
        ):
            return True
    return False


def pytest_configure(config):
    """Validate that no test is a no-op before running the suite."""
    # Scan all test files for empty/no-op tests and assertion-free tests
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

            # Check for no_assert marker (allowed exemption)
            if "no_assert" in decorators:
                continue  # Explicitly exempted from assertion requirement

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

            # No assertion or pytest.raises in body
            if not _has_assertion(node):
                issues.append(
                    f"{test_file.name}::{node.name} (no assertions found; "
                    "add @pytest.mark.no_assert if intentional)"
                )

    if issues:
        pytest.fail(
            "No-op or assertion-free tests detected:\n  "
            + "\n  ".join(issues)
            + "\n\nEach test must do actual work: make an assertion, use pytest.raises,"
            " call an assertion method like template.has_resource(), or mark with"
            " @pytest.mark.no_assert if no assertion is intentional."
        )
