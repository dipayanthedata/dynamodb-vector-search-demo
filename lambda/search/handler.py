"""Search Lambda: embeds a `query` via Bedrock Titan Text Embeddings V2 (same
model and dimension as ingest, imported from shared module), then searches the
vector index via SearchVectors. Returns scored results with measured timings.

Event shape: {"query": str, "top_k": int (default 5, 1-100), "category": str (optional)}.
If category is provided, filtered via SearchConditionExpression against the
INLINE_FILTER attribute (docs/api-notes.md's "Filtering design").

Response: list of {"docId": str, "score": float, "category": str|None, timings}.
Plus is_lower_better flag so callers know whether lower or higher scores indicate
similarity (per DistanceFunction per docs/api-notes.md).

Requires boto3/botocore new enough for search_vectors (docs/api-notes.md section (d)),
bundled as a Lambda layer.
"""

import json
import logging
import os
import time

import boto3

from shared.vector_config import (
    DISTANCE_FUNCTION,
    EMBEDDING_DIMENSIONS,
    VECTOR_INDEX_NAME,
)
from shared.vector_serialization import to_search_vector

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logger.info("boto3.__version__=%s", boto3.__version__)

TABLE_NAME = os.environ["TABLE_NAME"]
VECTOR_ATTRIBUTE_NAME = os.environ["VECTOR_ATTRIBUTE_NAME"]
CATEGORY_ATTRIBUTE_NAME = os.environ["CATEGORY_ATTRIBUTE_NAME"]
EMBEDDING_MODEL_ID = os.environ["EMBEDDING_MODEL_ID"]
EMBEDDING_NORMALIZE = os.environ["EMBEDDING_NORMALIZE"] == "true"

_dynamodb = boto3.client("dynamodb")
_bedrock = boto3.client("bedrock-runtime")

# Score direction per DistanceFunction (docs/api-notes.md score interpretation)
_SCORE_DIRECTION = {
    "COSINE": "asc",  # lower is better
    "EUCLIDEAN": "asc",  # lower is better
    "DOT_PRODUCT": "desc",  # higher is better
}


def handler(event, context):
    start_time = time.time()

    query = event["query"]
    top_k = event.get("top_k", 5)
    category = event.get("category")

    # Validate top_k (hard service limit per docs/api-notes.md (b))
    if not 1 <= top_k <= 100:
        raise ValueError(
            f"top_k must be 1-100 inclusive (DynamoDB service limit), got {top_k}"
        )

    embed_start = time.time()
    query_vector = _embed(query)
    embed_ms = (time.time() - embed_start) * 1000

    search_start = time.time()
    results = _search_vectors(query_vector, top_k, category)
    search_ms = (time.time() - search_start) * 1000

    total_ms = (time.time() - start_time) * 1000
    is_lower_better = _SCORE_DIRECTION[DISTANCE_FUNCTION] == "asc"

    response = {
        "results": results,
        "is_lower_better": is_lower_better,
        "timings": {
            "embed_ms": round(embed_ms, 2),
            "search_ms": round(search_ms, 2),
            "total_ms": round(total_ms, 2),
        },
    }
    logger.info(
        "Search query=%s top_k=%d category=%s results=%d timings=%s",
        query[:50],
        top_k,
        category,
        len(results),
        response["timings"],
    )
    return response


def _embed(query: str) -> list[float]:
    # Same model, dimensions, normalize as ingest (_embed in ingest/handler.py)
    response = _bedrock.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps(
            {
                "inputText": query,
                "dimensions": EMBEDDING_DIMENSIONS,
                "normalize": EMBEDDING_NORMALIZE,
            }
        ),
    )
    payload = json.loads(response["body"].read())
    embedding = payload["embedding"]
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Titan returned a {len(embedding)}-dimension embedding, expected "
            f"{EMBEDDING_DIMENSIONS} (EMBEDDING_DIMENSIONS) - "
            "shared/vector_config.py and the Bedrock request body are out of sync."
        )
    return embedding


def _search_vectors(
    query_vector: list[float], top_k: int, category: str | None
) -> list[dict]:
    # to_search_vector produces the bare array format (docs/api-notes.md (b)),
    # not L-wrapped. Never inline the format.
    search_vector = to_search_vector(query_vector)

    # SearchConditionExpression is optional; only set if category provided.
    # Equality only (docs/api-notes.md (b) SearchConditionExpression).
    kwargs = {
        "TableName": TABLE_NAME,
        "IndexName": VECTOR_INDEX_NAME,
        "SearchVector": search_vector,
        "TopK": top_k,
        "ProjectionExpression": "docId,#cat",  # Avoid 'category' keyword
        "ExpressionAttributeNames": {"#cat": CATEGORY_ATTRIBUTE_NAME},
    }

    if category is not None:
        kwargs["SearchConditionExpression"] = f"{CATEGORY_ATTRIBUTE_NAME} = :cat"
        kwargs["ExpressionAttributeValues"] = {":cat": {"S": category}}

    try:
        response = _dynamodb.search_vectors(**kwargs)
    except _dynamodb.exceptions.ResourceNotFoundException as e:
        # Index not found - check if it's the "not ACTIVE yet" case
        error_str = str(e)
        if "ACTIVE" in error_str or "Backfilling" in error_str:
            raise ValueError(
                f"Vector index {VECTOR_INDEX_NAME} is not yet ACTIVE. "
                "Wait a few minutes after deployment before searching. "
                f"Error: {e}"
            ) from e
        raise

    results = []
    for item in response.get("SearchResults", []):
        doc_id = item["Item"]["docId"]["S"]
        score = item["Score"]
        item_category = item["Item"].get(CATEGORY_ATTRIBUTE_NAME, {}).get("S")

        results.append(
            {
                "docId": doc_id,
                "score": score,
                "category": item_category,
            }
        )

    return results
