"""on_event / is_complete handlers for the vector index custom resource (CDK Provider
framework). Invoked by CloudFormation via the Provider's own state machine - never
called directly. Requires boto3/botocore >= 1.43.64 (bundled as a layer, not relying
on the Lambda runtime's own version - see docs/api-notes.md section (d)).

Create: adds the vector index via UpdateTable's VectorIndexUpdates, in the same call
adding the AttributeDefinitions entry the index's SearchSchema references (see
docs/api-notes.md section (a) - CreateTable/UpdateTable reject an AttributeDefinitions
entry unreferenced by any key schema/index in the same call).

Delete: removes the vector index the same way, tolerating the table or index already
being gone (e.g. the table itself was already deleted in the same stack teardown).

Update: not supported - see _on_update below for why, and why that's a stop rather
than a silent no-op.

Both is_complete paths fail loudly with a specific diagnostic message if they've been
polling past _MAX_WAIT_SECONDS, rather than polling forever until the Provider's own
total_timeout eventually fires with a generic message. _MAX_WAIT_SECONDS must stay
comfortably below the Provider's total_timeout (infra/custom_constructs/vector_index.py)
so our own message is what surfaces, not the framework's.
"""

import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ["TABLE_NAME"]
INDEX_NAME = os.environ["INDEX_NAME"]
VECTOR_ATTRIBUTE_NAME = os.environ["VECTOR_ATTRIBUTE_NAME"]
CATEGORY_ATTRIBUTE_NAME = os.environ["CATEGORY_ATTRIBUTE_NAME"]
DIMENSIONS = int(os.environ["DIMENSIONS"])
DISTANCE_FUNCTION = os.environ["DISTANCE_FUNCTION"]

# Provider's total_timeout is 15 minutes (infra/custom_constructs/vector_index.py) -
# this must stay under that with real margin, so a genuinely stuck index produces our
# own specific error (last observed IndexStatus/Backfilling/SearchVectors error) rather
# than the framework's generic timeout message.
_MAX_WAIT_SECONDS = 11 * 60

_client = boto3.client("dynamodb")


def on_event(event, context):
    request_type = event["RequestType"]
    logger.info("on_event RequestType=%s", request_type)
    if request_type == "Create":
        return _on_create()
    if request_type == "Delete":
        return _on_delete(event)
    if request_type == "Update":
        return _on_update()
    raise ValueError(f"Unknown RequestType: {request_type}")


def _on_create():
    response = _client.update_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": CATEGORY_ATTRIBUTE_NAME, "AttributeType": "S"},
        ],
        VectorIndexUpdates=[
            {
                "Create": {
                    "IndexName": INDEX_NAME,
                    "VectorAttribute": {"AttributeName": VECTOR_ATTRIBUTE_NAME},
                    "SearchSchema": [
                        {
                            "AttributeName": CATEGORY_ATTRIBUTE_NAME,
                            "SearchSchemaElementType": "INLINE_FILTER",
                        },
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                    "Dimensions": DIMENSIONS,
                    "DistanceFunction": DISTANCE_FUNCTION,
                }
            }
        ],
    )
    index_arn = _find_index_arn(response["TableDescription"].get("VectorIndexes", []))
    logger.info("UpdateTable (create) accepted, IndexArn=%s", index_arn)
    return {
        "PhysicalResourceId": index_arn or f"{TABLE_NAME}/index/{INDEX_NAME}",
        "Data": {"IndexArn": index_arn or "", "StartedAt": str(time.time())},
    }


def _on_delete(event):
    try:
        _client.update_table(
            TableName=TABLE_NAME,
            VectorIndexUpdates=[{"Delete": {"IndexName": INDEX_NAME}}],
        )
    except _client.exceptions.ResourceNotFoundException:
        # Table already gone (e.g. deleted earlier in the same stack teardown) -
        # nothing left to delete. Treat as success so teardown doesn't get stuck.
        logger.info("Table already gone on delete; treating as success")
    except ClientError as err:
        message = str(err.response.get("Error", {}).get("Message", ""))
        if "does not have the specified index" in message:
            logger.info("Index already gone on delete; treating as success")
        else:
            raise
    return {
        "PhysicalResourceId": event["PhysicalResourceId"],
        "Data": {"StartedAt": str(time.time())},
    }


def _on_update():
    # Every value that identifies this index (IndexName, Dimensions, DistanceFunction,
    # VectorAttributeName, CategoryAttributeName) is passed as a CustomResource property
    # (see infra/custom_constructs/vector_index.py), so CloudFormation only fires this
    # branch when one of them actually changes between deploys. Dimensions and
    # DistanceFunction are immutable after creation regardless (docs/api-notes.md
    # section (a)), and this demo's index is meant to be static - so a real change here
    # means delete-and-recreate is the right move, not an in-place mutation this handler
    # would have to reinvent. Failing loudly beats silently leaving the deployed index
    # out of sync with a config change that never got applied.
    raise RuntimeError(
        "Updating an existing vector index's identity (name, dimensions, distance "
        "function, vector/filter attribute names) is not supported by this custom "
        "resource. Delete and redeploy the stack instead."
    )


def _find_index_arn(vector_indexes):
    for index in vector_indexes:
        if index["IndexName"] == INDEX_NAME:
            return index.get("IndexArn")
    return None


def _elapsed_seconds(event):
    # The Provider framework merges whatever on_event returned (PhysicalResourceId,
    # Data) into the event object passed to each is_complete poll, so the StartedAt
    # timestamp on_event recorded is available here across every poll for the same
    # request. If that merge doesn't happen the way this assumes, default to "just
    # started" (elapsed=0) rather than raising a spurious timeout - worst case, this
    # degrades to relying on the Provider's own total_timeout as the only cap, not a
    # false failure.
    started_at = event.get("Data", {}).get("StartedAt")
    if started_at is None:
        return 0.0
    return time.time() - float(started_at)


def is_complete(event, context):
    request_type = event["RequestType"]
    elapsed = _elapsed_seconds(event)
    logger.info("is_complete RequestType=%s elapsed=%.0fs", request_type, elapsed)
    if request_type == "Create":
        return _is_create_complete(elapsed)
    if request_type == "Delete":
        return _is_delete_complete(elapsed)
    if request_type == "Update":
        # on_event already raised for Update before the Provider framework would ever
        # poll is_complete for one - unreachable in practice, kept only so an unknown/
        # future RequestType doesn't fall through silently.
        return {"IsComplete": True}
    raise ValueError(f"Unknown RequestType: {request_type}")


def _describe_index():
    try:
        table = _client.describe_table(TableName=TABLE_NAME)["Table"]
    except _client.exceptions.ResourceNotFoundException:
        return None
    for index in table.get("VectorIndexes", []):
        if index["IndexName"] == INDEX_NAME:
            return index
    return None


def _is_create_complete(elapsed):
    index = _describe_index()

    if (
        index is not None
        and index["IndexStatus"] == "ACTIVE"
        and not index.get("Backfilling")
    ):
        # DescribeTable reporting ACTIVE is necessary but not sufficient - the separate
        # SearchVectors endpoint can lag briefly after that (docs/api-notes.md
        # section (a)). A real SearchVectors call is the only fully reliable readiness
        # signal; a zero-magnitude probe vector is fine since we only care whether the
        # call is accepted at all, not the (meaningless) similarity results it returns.
        try:
            _client.search_vectors(
                TableName=TABLE_NAME,
                IndexName=INDEX_NAME,
                SearchVector=[{"N": "0.0"}] * DIMENSIONS,
                TopK=1,
            )
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "ValidationException":
                if elapsed > _MAX_WAIT_SECONDS:
                    raise RuntimeError(
                        f"Vector index '{INDEX_NAME}' reached IndexStatus=ACTIVE but "
                        f"SearchVectors still returns ValidationException after "
                        f"{elapsed:.0f}s: {err}. Search-endpoint propagation is taking "
                        "far longer than docs/api-notes.md section (a) describes as "
                        "typical - stopping rather than waiting indefinitely."
                    ) from err
                return {"IsComplete": False}
            raise
        return {"IsComplete": True}

    if elapsed > _MAX_WAIT_SECONDS:
        raise RuntimeError(
            f"Vector index '{INDEX_NAME}' did not reach IndexStatus=ACTIVE (with "
            f"Backfilling cleared) within {elapsed:.0f}s. Last observed index state: "
            f"{index!r}."
        )
    return {"IsComplete": False}


def _is_delete_complete(elapsed):
    index = _describe_index()
    if index is None:
        return {"IsComplete": True}
    if elapsed > _MAX_WAIT_SECONDS:
        raise RuntimeError(
            f"Vector index '{INDEX_NAME}' did not finish deleting within "
            f"{elapsed:.0f}s. Last observed index state: {index!r}."
        )
    return {"IsComplete": False}
