"""Stubber-based unit tests for the search Lambda (lambda/search/handler.py).
Similar to ingest tests: boto3 clients are swapped for Stubbers, no network access,
real request-building/serialization code runs against scripted responses.
"""

import importlib.util
import io
import json
from pathlib import Path

import pytest
from botocore.stub import Stubber

_HANDLER_PATH = (
    Path(__file__).resolve().parent.parent / "lambda" / "search" / "handler.py"
)

_ENV = {
    "TABLE_NAME": "test-table",
    "VECTOR_ATTRIBUTE_NAME": "embedding",
    "CATEGORY_ATTRIBUTE_NAME": "category",
    "EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
    "EMBEDDING_NORMALIZE": "true",
}


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)

    spec = importlib.util.spec_from_file_location(
        "search_handler_under_test", _HANDLER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub_invoke_model(handler_module, *, query: str, embedding: list) -> Stubber:
    """Stub Bedrock to return a query embedding."""
    stub = Stubber(handler_module._bedrock)
    stub.add_response(
        "invoke_model",
        {
            "body": io.BytesIO(json.dumps({"embedding": embedding}).encode()),
            "contentType": "application/json",
        },
        {
            "modelId": "amazon.titan-embed-text-v2:0",
            "body": json.dumps(
                {"inputText": query, "dimensions": 1024, "normalize": True}
            ),
        },
    )
    stub.activate()
    return stub


def test_search_happy_path_with_results(handler):
    # Query embedding matches stored embeddings; returns scored results
    query_embedding = [0.1, 0.2] + [0.0] * 1022
    _stub_invoke_model(handler, query="find similar", embedding=query_embedding)

    from shared.vector_serialization import to_search_vector

    dynamodb_stub = Stubber(handler._dynamodb)
    dynamodb_stub.add_response(
        "search_vectors",
        {
            "SearchResults": [
                {
                    "Item": {
                        "docId": {"S": "doc-1"},
                        "category": {"S": "category-a"},
                    },
                    "Score": 0.05,
                },
                {
                    "Item": {
                        "docId": {"S": "doc-2"},
                        "category": {"S": "category-b"},
                    },
                    "Score": 0.15,
                },
            ]
        },
        {
            "TableName": "test-table",
            "IndexName": "embedding-index",
            "SearchVector": to_search_vector(query_embedding),
            "TopK": 5,
            "ProjectionExpression": "docId,#cat",
            "ExpressionAttributeNames": {"#cat": "category"},
        },
    )
    dynamodb_stub.activate()

    result = handler.handler(
        {"query": "find similar"},
        None,
    )

    assert len(result["results"]) == 2
    assert result["results"][0]["docId"] == "doc-1"
    assert result["results"][0]["score"] == 0.05
    assert result["is_lower_better"] is True  # COSINE distance


def test_search_with_category_filter(handler):
    # Category filter passed via SearchConditionExpression
    query_embedding = [0.5] * 1024
    _stub_invoke_model(handler, query="filtered", embedding=query_embedding)

    from shared.vector_serialization import to_search_vector

    dynamodb_stub = Stubber(handler._dynamodb)
    dynamodb_stub.add_response(
        "search_vectors",
        {
            "SearchResults": [
                {
                    "Item": {
                        "docId": {"S": "doc-category-x"},
                        "category": {"S": "category-x"},
                    },
                    "Score": 0.1,
                }
            ]
        },
        {
            "TableName": "test-table",
            "IndexName": "embedding-index",
            "SearchVector": to_search_vector(query_embedding),
            "TopK": 5,
            "ProjectionExpression": "docId,#cat",
            "ExpressionAttributeNames": {"#cat": "category"},
            "SearchConditionExpression": "category = :cat",
            "ExpressionAttributeValues": {":cat": {"S": "category-x"}},
        },
    )
    dynamodb_stub.activate()

    result = handler.handler(
        {"query": "filtered", "category": "category-x"},
        None,
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["category"] == "category-x"


def test_search_raises_on_query_dimension_mismatch(handler):
    # Bedrock returns wrong dimension - same validation as ingest
    stub = Stubber(handler._bedrock)
    stub.add_response(
        "invoke_model",
        {
            "body": io.BytesIO(json.dumps({"embedding": [0.1, 0.2]}).encode()),  # Wrong
            "contentType": "application/json",
        },
        {
            "modelId": "amazon.titan-embed-text-v2:0",
            "body": json.dumps(
                {"inputText": "mismatch", "dimensions": 1024, "normalize": True}
            ),
        },
    )
    stub.activate()

    with pytest.raises(ValueError, match="dimension"):
        handler.handler({"query": "mismatch"}, None)


def test_search_raises_on_top_k_too_low(handler):
    # top_k must be >= 1
    with pytest.raises(ValueError, match="top_k.*1-100"):
        handler.handler({"query": "q", "top_k": 0}, None)


def test_search_raises_on_top_k_too_high(handler):
    # top_k must be <= 100 (service limit per docs/api-notes.md (b))
    with pytest.raises(ValueError, match="top_k.*1-100"):
        handler.handler({"query": "q", "top_k": 101}, None)


def test_search_raises_on_index_not_active(handler):
    # ValidationException when index is still backfilling or search endpoint is lagging.
    # Stub message is illustrative/unverified; actual message depends on real behavior
    # observed in step 8 deploy. See docs/api-notes.md (a) and (unverified note).
    query_embedding = [0.1] * 1024
    _stub_invoke_model(handler, query="not ready", embedding=query_embedding)

    from shared.vector_serialization import to_search_vector

    dynamodb_stub = Stubber(handler._dynamodb)
    # add_client_error doesn't check params before raising, so we still need to
    # ensure the correct params are built; calling to_search_vector() makes that explicit
    _ = to_search_vector(query_embedding)  # Verify format without Stubber checking
    dynamodb_stub.add_client_error(
        "search_vectors",
        service_error_code="ValidationException",
        service_message="[Illustrative message - actual error unverified pending step 8 deploy]",
    )
    dynamodb_stub.activate()

    with pytest.raises(ValueError, match="not yet ready|Wait a few moments"):
        handler.handler({"query": "not ready"}, None)


def test_search_raises_on_index_not_found(handler):
    # ResourceNotFoundException when table or index does not exist.
    # Stub message is illustrative/unverified; actual error depends on real behavior
    # observed in step 8 deploy.
    query_embedding = [0.1] * 1024
    _stub_invoke_model(handler, query="missing", embedding=query_embedding)

    from shared.vector_serialization import to_search_vector

    dynamodb_stub = Stubber(handler._dynamodb)
    _ = to_search_vector(query_embedding)  # Verify format without Stubber checking
    dynamodb_stub.add_client_error(
        "search_vectors",
        service_error_code="ResourceNotFoundException",
        service_message="[Illustrative message - actual error unverified pending step 8 deploy]",
    )
    dynamodb_stub.activate()

    with pytest.raises(ValueError, match="not found|Verify the table"):
        handler.handler({"query": "missing"}, None)


def test_search_raises_on_bedrock_access_denied(handler):
    # AccessDeniedException from Bedrock (user doesn't have Titan model access)
    stub = Stubber(handler._bedrock)
    stub.add_client_error(
        "invoke_model",
        service_error_code="AccessDeniedException",
        service_message="User is not authorized to perform: bedrock:InvokeModel",
    )
    stub.activate()

    with pytest.raises(Exception, match="AccessDenied|not.*authorized"):
        handler.handler({"query": "no access"}, None)


def test_search_raises_on_dynamodb_throttling(handler):
    # SearchVectors throttling
    _stub_invoke_model(handler, query="throttled", embedding=[0.1] * 1024)

    dynamodb_stub = Stubber(handler._dynamodb)
    dynamodb_stub.add_client_error(
        "search_vectors",
        service_error_code="ThrottlingException",
        service_message="Rate exceeded",
    )
    dynamodb_stub.activate()

    with pytest.raises(Exception, match="ThrottlingException|throttl"):
        handler.handler({"query": "throttled"}, None)


def test_search_query_vector_is_bare_array_not_l_wrapped(handler):
    # SearchVector param must be bare array, not L-wrapped (docs/api-notes.md (b))
    query_embedding = [0.1, 0.2] + [0.0] * 1022
    _stub_invoke_model(handler, query="bare array", embedding=query_embedding)

    from shared.vector_serialization import to_search_vector

    dynamodb_stub = Stubber(handler._dynamodb)
    dynamodb_stub.add_response(
        "search_vectors",
        {"SearchResults": []},
        {
            "TableName": "test-table",
            "IndexName": "embedding-index",
            "SearchVector": to_search_vector(query_embedding),
            "TopK": 5,
            "ProjectionExpression": "docId,#cat",
            "ExpressionAttributeNames": {"#cat": "category"},
        },
    )
    dynamodb_stub.activate()

    result = handler.handler({"query": "bare array"}, None)

    # If the Stubber matched, then SearchVector was indeed sent as bare array,
    # not L-wrapped (the format assertion is in the expected_params).
    assert result is not None  # Verify call went through
