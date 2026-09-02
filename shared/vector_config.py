"""Single source of truth for names/values that must agree across the CDK app
(infra/) and the Lambda handlers (lambda/) - imported by both, never duplicated.

If these drift independently (e.g. the vector index's Dimensions on one side and
the embedding model's requested dimensions on the other), writes and searches
fail with a dimension-mismatch error at call time, not at synth time - see
docs/api-notes.md section (a): "Dimensions must match the vector length written
to items; mismatches are rejected on write."
"""

# Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0) supports 256, 512,
# or 1024 output dimensions. 1024 is the model default and gives the best retrieval
# quality of the three - see docs/api-notes.md's "Bedrock Titan Text Embeddings V2"
# section for the full reasoning (the per-dimension cost delta is negligible at this
# demo's corpus scale regardless of which is chosen).
EMBEDDING_DIMENSIONS = 1024

# COSINE | DOT_PRODUCT | EUCLIDEAN - see docs/api-notes.md section (a). Immutable
# after index creation (confirmed in the same section); changing this requires
# deleting and recreating the vector index.
DISTANCE_FUNCTION = "COSINE"

# The item attribute holding the vector embedding (VectorAttribute.AttributeName
# in the vector index's Create action - docs/api-notes.md section (a)).
VECTOR_ATTRIBUTE_NAME = "embedding"

# The vector index's name (IndexName param to UpdateTable/SearchVectors).
VECTOR_INDEX_NAME = "embedding-index"

# The item attribute used as the vector index's INLINE_FILTER - see
# docs/api-notes.md's "Filtering design for this demo". Optional at query time,
# unlike a HASH search-schema element, which this demo deliberately does not use.
CATEGORY_ATTRIBUTE_NAME = "category"
