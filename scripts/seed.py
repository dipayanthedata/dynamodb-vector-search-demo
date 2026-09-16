#!/usr/bin/env python3
"""Seed the DynamoDB vector search demo with corpus documents.

Invokes the ingest Lambda per document in data/corpus.json, with progress output.
Polls until every item has an embedding attribute (synchronous), then reports
total wall-clock time and document count.

Usage: python3 scripts/seed.py
"""

import json
import os
import sys
import time
from pathlib import Path

import boto3

# Find repo root (one level up from scripts/)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CORPUS_PATH = _REPO_ROOT / "data" / "corpus.json"

# Lambda function name comes from CDK stack (infra/lib/dynamodb_vector_search_stack.py)
# Can be overridden via INGEST_FUNCTION_NAME env var
_LAMBDA_FUNCTION_NAME = os.environ.get(
    "INGEST_FUNCTION_NAME", "DynamoDBVectorSearchDemo-IngestHandler"
)

_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_lambda_client = boto3.client("lambda", region_name=_REGION)
_dynamodb_client = boto3.client("dynamodb", region_name=_REGION)


def main():
    """Load corpus, invoke Lambda per document, poll for completion."""
    if not _CORPUS_PATH.exists():
        print(f"Error: corpus not found at {_CORPUS_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(_CORPUS_PATH) as f:
        corpus = json.load(f)

    if not corpus:
        print("Error: corpus is empty", file=sys.stderr)
        sys.exit(1)

    table_name = os.environ.get("TABLE_NAME", "dynamodb-vector-search-demo")
    vector_attr = os.environ.get("VECTOR_ATTRIBUTE_NAME", "embedding")

    print(f"Seeding {len(corpus)} documents into {table_name}...")
    start_time = time.time()

    # Invoke Lambda for each document
    for i, doc in enumerate(corpus, 1):
        doc_id = doc["docId"]
        text = doc["text"]
        category = doc.get("category")

        event = {
            "docId": doc_id,
            "text": text,
        }
        if category:
            event["category"] = category

        try:
            response = _lambda_client.invoke(
                FunctionName=_LAMBDA_FUNCTION_NAME,
                InvocationType="RequestResponse",
                Payload=json.dumps(event),
            )
            if response["StatusCode"] != 200:
                print(
                    f"  [{i}/{len(corpus)}] {doc_id}: Lambda error (status {response['StatusCode']})",
                    file=sys.stderr,
                )
                continue

            payload = json.loads(response.get("Payload", b"{}").read())
            if "FunctionError" in response:
                print(
                    f"  [{i}/{len(corpus)}] {doc_id}: invocation failed - {payload}",
                    file=sys.stderr,
                )
            else:
                print(f"  [{i}/{len(corpus)}] {doc_id}: ingested")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  [{i}/{len(corpus)}] {doc_id}: exception - {e}", file=sys.stderr)

    # Poll until all documents have embeddings
    print("\nWaiting for all embeddings to be written...")
    poll_interval = 2
    poll_timeout = 120
    poll_elapsed = 0
    last_count = 0

    while poll_elapsed < poll_timeout:
        try:
            response = _dynamodb_client.scan(
                TableName=table_name,
                ProjectionExpression="docId",
                FilterExpression="attribute_exists(#emb)",
                ExpressionAttributeNames={"#emb": vector_attr},
            )
            count = response.get("Count", 0)
            if count != last_count:
                print(f"  {count}/{len(corpus)} documents have embeddings")
                last_count = count
            if count >= len(corpus):
                break
        except KeyError as e:
            print(f"  Scan error: {e}", file=sys.stderr)

        time.sleep(poll_interval)
        poll_elapsed += poll_interval

    elapsed = time.time() - start_time
    print(f"\n✅ Seeded {len(corpus)} documents in {elapsed:.1f}s")
    print(f"   Average: {elapsed / len(corpus):.2f}s per document")


if __name__ == "__main__":
    main()
