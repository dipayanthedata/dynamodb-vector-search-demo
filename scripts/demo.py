#!/usr/bin/env python3
"""Demonstrate DynamoDB vector search with curated queries.

Shows 6 queries with top 3 results, scores, and performance timings.
Includes category filtering example and score direction interpretation.

Usage: python3 scripts/demo.py
"""

import json
import sys

import boto3

# Lambda function names from CDK stack
_LAMBDA_SEARCH = "DynamoDBVectorSearchDemo-SearchHandler"
_lambda_client = boto3.client("lambda")


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

    # Query 1: Semantic match - "rapid transportation" should match docs about fast travel
    print("\n[Query 1] Semantic match - 'rapid transportation'")
    print("(Should match docs about fast travel methods)")
    try:
        results = _invoke_search("rapid transportation")
        _print_results("rapid transportation", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 2: Semantic match - "monetary exchange" should match docs about trading/currency
    print("\n" + "=" * 70)
    print("[Query 2] Semantic match - 'monetary exchange'")
    print("(Should match business/finance docs about money and trading)")
    try:
        results = _invoke_search("monetary exchange")
        _print_results("monetary exchange", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 3: Keyword match - "artificial intelligence"
    print("\n" + "=" * 70)
    print("[Query 3] Keywords present - 'artificial intelligence'")
    print("(Should match tech docs with explicit keywords)")
    try:
        results = _invoke_search("artificial intelligence")
        _print_results("artificial intelligence", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 4: Semantic match - "learning systems" as paraphrase for ML
    print("\n" + "=" * 70)
    print("[Query 4] Semantic match - 'automatic learning systems'")
    print("(Paraphrase of machine learning - no exact keyword match)")
    try:
        results = _invoke_search("automatic learning systems")
        _print_results("automatic learning systems", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 5: With category filter - unfiltered first, then filtered
    print("\n" + "=" * 70)
    print("[Query 5a] Unfiltered - 'healing processes' (all categories)")
    print("(Should match health docs)")
    try:
        results = _invoke_search("healing processes")
        _print_results("healing processes", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    print("\n[Query 5b] SAME QUERY with category filter: health only")
    print("(Results should be filtered to health category only)")
    try:
        results = _invoke_search("healing processes", category="health")
        _print_results("healing processes (category=health)", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    # Query 6: Semantic - "physician" should match "doctors" and medical professionals
    print("\n" + "=" * 70)
    print("[Query 6] Semantic match - 'physician expertise'")
    print("(Should match health docs about doctors and medical professionals)")
    try:
        results = _invoke_search("physician expertise")
        _print_results("physician expertise", results)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)

    print("\n" + "=" * 70)
    print("Demo complete")


if __name__ == "__main__":
    main()
