"""Ingest Lambda: embeds `text` via Bedrock Titan Text Embeddings V2 and writes the
resulting item (with its vector, in the shape docs/api-notes.md section (b) calls
for) to the base table via PutItem. Invoked directly - no API Gateway
(CLAUDE.md) - e.g. by a script in a later build step.

Event shape: {"docId": str, "text": str, "category": str (optional)}. `category`
is the vector index's INLINE_FILTER attribute (shared/vector_config.py,
CATEGORY_ATTRIBUTE_NAME) - optional at query time, so an item without it is still
written and still searchable, just not filterable by category
(docs/api-notes.md's "Filtering design for this demo": this demo's index defines
no HASH element, so - unlike a missing HASH attribute - a missing INLINE_FILTER
attribute does not exclude the item from the vector index).

Requires boto3/botocore new enough for search_vectors/VectorIndexUpdates
(docs/api-notes.md section (d)), bundled as a Lambda layer rather than trusting
the managed runtime's own bundled version. boto3.__version__ is logged at module
scope (cold start) so a layer that failed to attach, or got shadowed by the
runtime's own older version, surfaces immediately as a visible version log line -
not as an unrelated AttributeError deeper in the call stack once a boto3 call
tries to use an API the shadowing version doesn't have.
"""

import json
import logging
import os

import boto3

from shared.vector_serialization import to_stored_vector

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logger.info("boto3.__version__=%s", boto3.__version__)

TABLE_NAME = os.environ["TABLE_NAME"]
VECTOR_ATTRIBUTE_NAME = os.environ["VECTOR_ATTRIBUTE_NAME"]
CATEGORY_ATTRIBUTE_NAME = os.environ["CATEGORY_ATTRIBUTE_NAME"]
EMBEDDING_MODEL_ID = os.environ["EMBEDDING_MODEL_ID"]
EMBEDDING_DIMENSIONS = int(os.environ["EMBEDDING_DIMENSIONS"])
EMBEDDING_NORMALIZE = os.environ["EMBEDDING_NORMALIZE"] == "true"

_dynamodb = boto3.client("dynamodb")
_bedrock = boto3.client("bedrock-runtime")


def handler(event, context):
    doc_id = event["docId"]
    text = event["text"]
    category = event.get("category")

    embedding = _embed(text)

    item = {
        "docId": {"S": doc_id},
        "text": {"S": text},
        VECTOR_ATTRIBUTE_NAME: to_stored_vector(embedding),
    }
    if category is not None:
        item[CATEGORY_ATTRIBUTE_NAME] = {"S": category}

    _dynamodb.put_item(TableName=TABLE_NAME, Item=item)
    logger.info("Ingested docId=%s category=%s", doc_id, category)
    return {"docId": doc_id}


def _embed(text: str) -> list[float]:
    # Request/response field names and the dimensions/normalize semantics are all
    # verbatim from docs/api-notes.md's "Bedrock Titan Text Embeddings V2" section.
    response = _bedrock.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps(
            {
                "inputText": text,
                "dimensions": EMBEDDING_DIMENSIONS,
                "normalize": EMBEDDING_NORMALIZE,
            }
        ),
    )
    payload = json.loads(response["body"].read())
    embedding = payload["embedding"]
    if len(embedding) != EMBEDDING_DIMENSIONS:
        # Titan's `dimensions` request field and this vector index's own
        # `Dimensions` (shared/vector_config.py's EMBEDDING_DIMENSIONS) must always
        # agree - a mismatch here would otherwise surface later, as a write-time
        # rejection from DynamoDB instead of a clear error from the value that
        # actually diverged.
        raise ValueError(
            f"Titan returned a {len(embedding)}-dimension embedding, expected "
            f"{EMBEDDING_DIMENSIONS} (EMBEDDING_DIMENSIONS) - "
            "shared/vector_config.py and the Bedrock request body are out of sync."
        )
    return embedding
