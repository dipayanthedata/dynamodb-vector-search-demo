"""Stubber-based unit tests for the ingest Lambda (lambda/ingest/handler.py). Its
two boto3 clients (Bedrock Runtime, DynamoDB) are swapped for
botocore.stub.Stubber doubles so the real request-building/serialization code runs
against a scripted response, with no network access and no real AWS resources.

lambda/ingest/handler.py sits under `lambda/`, which is a Python reserved word, so
it can't be imported with normal package syntax (`import lambda.ingest.handler`
is a SyntaxError). It's loaded here via importlib.util.spec_from_file_location
under a synthetic module name instead, which also sidesteps a name collision with
lambda/vector_index_manager/handler.py - both files are literally named
handler.py.
"""

import importlib.util
import io
import json
from pathlib import Path

import pytest
from botocore.stub import Stubber

_HANDLER_PATH = (
    Path(__file__).resolve().parent.parent / "lambda" / "ingest" / "handler.py"
)

_ENV = {
    "TABLE_NAME": "test-table",
    "VECTOR_ATTRIBUTE_NAME": "embedding",
    "CATEGORY_ATTRIBUTE_NAME": "category",
    "EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
    "EMBEDDING_DIMENSIONS": "3",
    "EMBEDDING_NORMALIZE": "true",
}


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)

    spec = importlib.util.spec_from_file_location(
        "ingest_handler_under_test", _HANDLER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub_invoke_model(handler_module, *, input_text: str, embedding: list) -> Stubber:
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
                {"inputText": input_text, "dimensions": 3, "normalize": True}
            ),
        },
    )
    stub.activate()
    return stub


def test_ingest_embeds_and_puts_item_with_category(handler):
    bedrock_stub = _stub_invoke_model(
        handler, input_text="hello world", embedding=[0.1, -0.2, 0.3]
    )

    dynamodb_stub = Stubber(handler._dynamodb)
    dynamodb_stub.add_response(
        "put_item",
        {},
        {
            "TableName": "test-table",
            "Item": {
                "docId": {"S": "doc-1"},
                "text": {"S": "hello world"},
                "embedding": {"L": [{"N": "0.1"}, {"N": "-0.2"}, {"N": "0.3"}]},
                "category": {"S": "demo"},
            },
        },
    )
    dynamodb_stub.activate()

    result = handler.handler(
        {"docId": "doc-1", "text": "hello world", "category": "demo"}, None
    )

    bedrock_stub.assert_no_pending_responses()
    dynamodb_stub.assert_no_pending_responses()
    assert result == {"docId": "doc-1"}


def test_ingest_without_category_omits_category_attribute(handler):
    _stub_invoke_model(handler, input_text="no category", embedding=[1.0, 0.0, -1.0])

    dynamodb_stub = Stubber(handler._dynamodb)
    dynamodb_stub.add_response(
        "put_item",
        {},
        {
            "TableName": "test-table",
            "Item": {
                "docId": {"S": "doc-2"},
                "text": {"S": "no category"},
                "embedding": {"L": [{"N": "1.0"}, {"N": "0.0"}, {"N": "-1.0"}]},
            },
        },
    )
    dynamodb_stub.activate()

    result = handler.handler({"docId": "doc-2", "text": "no category"}, None)

    dynamodb_stub.assert_no_pending_responses()
    assert result == {"docId": "doc-2"}


def test_ingest_raises_on_embedding_dimension_mismatch(handler):
    _stub_invoke_model(handler, input_text="wrong size", embedding=[0.1, 0.2])

    with pytest.raises(ValueError, match="dimension"):
        handler.handler({"docId": "doc-3", "text": "wrong size"}, None)


def test_ingest_raises_on_bedrock_throttling(handler):
    # Bedrock throttling is a transient error; handler should propagate it clearly
    stub = Stubber(handler._bedrock)
    stub.add_client_error(
        "invoke_model",
        service_error_code="ThrottlingException",
        service_message="Rate exceeded",
    )
    stub.activate()

    with pytest.raises(Exception, match="ThrottlingException|throttl"):
        handler.handler({"docId": "doc-4", "text": "throttled"}, None)


def test_ingest_raises_on_bedrock_access_denied(handler):
    # AccessDeniedException means user doesn't have Titan model access - error must be clear
    stub = Stubber(handler._bedrock)
    stub.add_client_error(
        "invoke_model",
        service_error_code="AccessDeniedException",
        service_message="User is not authorized to perform: bedrock:InvokeModel on resource",
    )
    stub.activate()

    with pytest.raises(
        Exception, match="AccessDenied|Titan|not.*authorized|permission"
    ):
        handler.handler({"docId": "doc-5", "text": "no access"}, None)


def test_ingest_raises_on_malformed_embedding_response(handler):
    # Bedrock response missing embedding field
    stub = Stubber(handler._bedrock)
    stub.add_response(
        "invoke_model",
        {
            "body": io.BytesIO(json.dumps({"inputTextTokenCount": 5}).encode()),
            "contentType": "application/json",
        },
        {
            "modelId": "amazon.titan-embed-text-v2:0",
            "body": json.dumps(
                {"inputText": "malformed", "dimensions": 3, "normalize": True}
            ),
        },
    )
    stub.activate()

    with pytest.raises(KeyError, match="embedding"):
        handler.handler({"docId": "doc-6", "text": "malformed"}, None)


def test_ingest_raises_on_dynamodb_put_failure(handler):
    # DynamoDB write fails
    _stub_invoke_model(handler, input_text="db error", embedding=[0.5, 0.5, 0.5])

    dynamodb_stub = Stubber(handler._dynamodb)
    dynamodb_stub.add_client_error(
        "put_item",
        service_error_code="ValidationException",
        service_message="One or more parameter values are invalid",
    )
    dynamodb_stub.activate()

    with pytest.raises(Exception, match="ValidationException"):
        handler.handler({"docId": "doc-7", "text": "db error"}, None)
