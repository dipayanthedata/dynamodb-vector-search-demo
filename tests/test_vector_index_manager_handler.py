"""Unit tests for the vector index manager custom resource handlers.

Tests the on_event and is_complete handlers that manage vector index creation/deletion
via UpdateTable. Uses Stubber to mock DynamoDB calls without network access.
"""

import importlib.util
from pathlib import Path

import pytest
from botocore.stub import Stubber

_HANDLER_PATH = (
    Path(__file__).resolve().parent.parent
    / "lambda"
    / "vector_index_manager"
    / "handler.py"
)

_ENV = {
    "TABLE_NAME": "test-table",
    "INDEX_NAME": "test-index",
    "VECTOR_ATTRIBUTE_NAME": "embedding",
    "CATEGORY_ATTRIBUTE_NAME": "category",
    "DIMENSIONS": "1024",
    "DISTANCE_FUNCTION": "COSINE",
}


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)

    spec = importlib.util.spec_from_file_location(
        "vector_index_manager_under_test", _HANDLER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_on_delete_calls_update_table_with_delete(handler):
    """_on_delete issues UpdateTable with VectorIndexUpdates[].Delete for the index."""
    stub = Stubber(handler._client)
    stub.add_response(
        "update_table",
        {
            "TableDescription": {
                "TableName": "test-table",
                "TableStatus": "UPDATING",
                "VectorIndexes": [],
            }
        },
        {
            "TableName": "test-table",
            "VectorIndexUpdates": [{"Delete": {"IndexName": "test-index"}}],
        },
    )
    stub.activate()

    result = handler._on_delete(
        {
            "PhysicalResourceId": "arn:aws:dynamodb:us-east-1:123456789012:table/test-table/index/test-index"
        }
    )

    stub.assert_no_pending_responses()
    assert result["PhysicalResourceId"]
    assert "Data" in result


def test_on_delete_treats_table_not_found_as_success(handler):
    """_on_delete succeeds if table is already gone (e.g., deleted earlier in teardown)."""
    stub = Stubber(handler._client)
    stub.add_client_error(
        "update_table",
        service_error_code="ResourceNotFoundException",
        service_message="Requested resource not found",
    )
    stub.activate()

    result = handler._on_delete(
        {
            "PhysicalResourceId": "arn:aws:dynamodb:us-east-1:123456789012:table/test-table/index/test-index"
        }
    )

    assert result["PhysicalResourceId"]


def test_on_delete_treats_index_not_found_as_success(handler):
    """_on_delete succeeds if index is already gone (e.g., removed earlier in teardown)."""
    stub = Stubber(handler._client)
    stub.add_client_error(
        "update_table",
        service_error_code="ValidationException",
        service_message="table does not have the specified index",
    )
    stub.activate()

    result = handler._on_delete(
        {
            "PhysicalResourceId": "arn:aws:dynamodb:us-east-1:123456789012:table/test-table/index/test-index"
        }
    )

    assert result["PhysicalResourceId"]


def test_on_delete_propagates_other_errors(handler):
    """_on_delete raises on unexpected DynamoDB errors."""
    stub = Stubber(handler._client)
    stub.add_client_error(
        "update_table",
        service_error_code="AccessDeniedException",
        service_message="User is not authorized",
    )
    stub.activate()

    with pytest.raises(Exception, match="AccessDenied|not.*authorized"):
        handler._on_delete(
            {
                "PhysicalResourceId": "arn:aws:dynamodb:us-east-1:123456789012:table/test-table/index/test-index"
            }
        )
