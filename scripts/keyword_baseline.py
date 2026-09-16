#!/usr/bin/env python3
"""Naive keyword search baseline for comparison with vector search.

Uses Scan with FilterExpression contains() on the same queries as demo.py,
reporting results in the same format so the two can be compared side by side.
Also reports Scan's consumed capacity and latency.

Usage: python3 scripts/keyword_baseline.py
"""

import os
import sys
import time
from pathlib import Path

import boto3

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CORPUS_PATH = _REPO_ROOT / "data" / "corpus.json"

_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_dynamodb = boto3.client("dynamodb", region_name=_REGION)


def _keyword_search(query: str, category: str | None = None) -> dict:
    """Naive keyword search using Scan with contains().

    Returns results in same shape as vector search for comparison.
    """
    start_time = time.time()

    # Split query into keywords (naive tokenization)
    keywords = query.lower().split()

    # Build a FilterExpression that checks if text contains any keyword
    # DynamoDB's contains() is case-sensitive, so we'd need a more complex setup
    # for case-insensitive search. For this demo, we'll do a simpler approach:
    # Scan all items and filter in Python.

    table_name = os.environ.get("TABLE_NAME", "dynamodb-vector-search-demo")

    try:
        response = _dynamodb.scan(TableName=table_name)
    except boto3.exceptions.Boto3Error as e:
        raise RuntimeError(f"Scan failed: {e}")

    items = response.get("Items", [])
    matches = []

    for item in items:
        text = item.get("text", {}).get("S", "").lower()
        cat = item.get("category", {}).get("S", "")

        # Skip if category filter doesn't match
        if category and cat != category:
            continue

        # Check if any keyword appears in text
        match_count = sum(1 for kw in keywords if kw in text)
        if match_count > 0:
            matches.append(
                {
                    "docId": item.get("docId", {}).get("S", ""),
                    "category": cat,
                    "keyword_matches": match_count,
                    "text": text[:80] + ("..." if len(text) > 80 else ""),
                }
            )

    # Sort by number of keyword matches (descending), then by docId
    matches.sort(key=lambda x: (-x["keyword_matches"], x["docId"]))

    elapsed_ms = (time.time() - start_time) * 1000
    consumed_rcu = response.get("ConsumedCapacity", {}).get("CapacityUnits", 0)

    return {
        "results": matches[:3],  # Top 3 for consistency with vector search
        "total_matches": len(matches),
        "consumed_rcu": consumed_rcu,
        "scan_latency_ms": elapsed_ms,
    }


def _print_results(query: str, results: dict):
    """Print keyword search results in comparable format."""
    print(f"\nQuery: {query}")
    print(
        f"Keyword matches: {len(results['results'])}/{results['total_matches']} shown"
    )
    print(f"Scan latency: {results['scan_latency_ms']:.1f}ms")
    print(f"Consumed capacity: {results['consumed_rcu']} RCU")

    for i, result in enumerate(results["results"], 1):
        doc_id = result["docId"]
        category = result.get("category", "—")
        kw_matches = result["keyword_matches"]
        print(f"  {i}. {doc_id:<15} matches={kw_matches}  category={category}")
        print(f"     {result['text']}")


def main():
    """Run keyword search on the same queries as demo.py."""
    print("=" * 70)
    print("Keyword Search Baseline (for comparison)")
    print("=" * 70)

    queries = [
        ("rapid transportation", None),
        ("monetary exchange", None),
        ("machine learning", None),
        ("foundational connectivity infrastructure", None),
        ("healing processes", None),
        ("healing processes", "health"),
        ("physician expertise", None),
    ]

    for query, category in queries:
        if category:
            print(f"\n[Query] '{query}' with category filter: {category}")
        else:
            print(f"\n[Query] '{query}'")

        try:
            results = _keyword_search(query, category=category)
            _print_results(query, results)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)

        print("-" * 70)

    print("\n" + "=" * 70)
    print("Observations:")
    print("- Vector search uses semantic understanding of meaning")
    print("- Keyword search matches only if query words appear in text")
    print("- Some queries have no keyword matches but strong semantic matches")
    print("- Scan latency grows with corpus size; vector search latency is stable")


if __name__ == "__main__":
    main()
