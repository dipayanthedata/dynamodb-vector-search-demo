#!/usr/bin/env python3
"""Demonstrate DynamoDB vector search with curated queries.

Shows 6 queries with top 3 results, scores, and performance timings.
Includes category filtering example and score direction interpretation.

Usage: python3 scripts/demo.py
"""

import json
import os
import sys

import boto3

# Lambda function names from CDK stack (can override via SEARCH_FUNCTION_NAME env var)
_LAMBDA_SEARCH = os.environ.get(
    "SEARCH_FUNCTION_NAME", "DynamoDBVectorSearchDemo-SearchHandler"
)
_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_lambda_client = boto3.client("lambda", region_name=_REGION)


def _invoke_search(query: str, top_k: int = 3, category: str | None = None) -> dict:
    """Invoke the search Lambda and return results."""
    event = {"query": query, "top_k": top_k}
    if category:
        event["category"] = category

    response = _lambda_client.invoke(
        FunctionName=_LAMBDA_SEARCH,
        InvocationType="RequestResponse",
        Payload=json.dumps(event),
    )

    if response["StatusCode"] != 200:
        raise RuntimeError(f"Lambda error: status {response['StatusCode']}")

    payload = json.loads(response.get("Payload", b"{}").read())
    if "FunctionError" in response:
        raise RuntimeError(f"Invocation failed: {payload}")

    return payload


class LambdaInvocationError(RuntimeError):
    """Raised when Lambda invocation fails."""


def _print_results(query: str, results: dict):
    """Print search results in readable format."""
    print(f"\nQuery: {query}")
    is_lower_better = results["is_lower_better"]
    direction = "↓ lower is better" if is_lower_better else "↑ higher is better"
    print(f"Score direction: {direction}")
    print(
        f"Timings: embed={results['timings']['embed_ms']:.1f}ms, "
        f"search={results['timings']['search_ms']:.1f}ms, "
        f"total={results['timings']['total_ms']:.1f}ms"
    )

    for i, result in enumerate(results["results"], 1):
        score = result["score"]
        doc_id = result["docId"]
        category = result.get("category", "—")
        print(f"  {i}. {doc_id:<15} score={score:.4f}  category={category}")


def main():
    """Run demonstration queries."""
    print("=" * 70)
    print("DynamoDB Vector Search Demo")
    print("=" * 70)

    # Query 1: Semantic-only - no keyword matches in expected results
    print("\n[Query 1] Semantic-only - 'rapid transportation'")
    print("(No keywords match expected travel docs)")
    try:
        results = _invoke_search("rapid transportation")
        _print_results("rapid transportation", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 2: Mixed - partial keyword matches
    print("\n" + "=" * 70)
    print("[Query 2] Mixed - 'monetary exchange'")
    print("(Some keyword matches in business docs)")
    try:
        results = _invoke_search("monetary exchange")
        _print_results("monetary exchange", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 3: Keyword-favorable - keywords present
    print("\n" + "=" * 70)
    print("[Query 3] Keyword-favorable - 'machine learning'")
    print("(Keywords explicitly present in results)")
    try:
        results = _invoke_search("machine learning")
        _print_results("machine learning", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 4: Semantic-only - no keyword matches
    print("\n" + "=" * 70)
    print("[Query 4] Semantic-only - 'foundational connectivity infrastructure'")
    print("(Complex semantic query, no direct keywords match)")
    try:
        results = _invoke_search("foundational connectivity infrastructure")
        _print_results("foundational connectivity infrastructure", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 5: Mixed - with category filter demonstration
    print("\n" + "=" * 70)
    print("[Query 5a] Mixed (unfiltered) - 'healing processes'")
    print("(Some keyword matches in health docs, all categories)")
    try:
        results = _invoke_search("healing processes")
        _print_results("healing processes", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    print("\n[Query 5b] SAME QUERY with category filter: health only")
    print("(Compare unfiltered vs. filtered results)")
    try:
        results = _invoke_search("healing processes", category="health")
        _print_results("healing processes (category=health)", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 6: Semantic-only - no keyword matches
    print("\n" + "=" * 70)
    print("[Query 6] Semantic-only - 'physician expertise'")
    print("(No keywords match health docs)")
    try:
        results = _invoke_search("physician expertise")
        _print_results("physician expertise", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    print("\n" + "=" * 70)
    print("Demo complete")


if __name__ == "__main__":
    main()
