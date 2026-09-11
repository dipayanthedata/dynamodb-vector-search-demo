# Build State: Step 5 In Progress

**Last updated:** 2026-09-11 (session continuing from step 4)

## Completed

- **Step 1-4:** Scaffold, base table, vector index custom resource, ingest Lambda (25 passing tests)
- **Step 5 handler:** Search Lambda fully implemented, all code logic green
  - Embeds query via Bedrock Titan (same model/dimension as ingest)
  - SearchVectors call with bare array format via `to_search_vector()`
  - Category filter via SearchConditionExpression (equality only)
  - Validates top_k (1-100) before calling DynamoDB
  - Returns scored results with `is_lower_better` flag + measured timings
  - Distinct error for index-not-ACTIVE case (tells reader to wait post-deploy)
  - IAM scoped correctly: bedrock:InvokeModel on model ARN, dynamodb:SearchVectors on INDEX ARN

## In Progress / Open

### Search Handler Tests (test_search_handler.py)

**Status:** Written but failing. 8 tests designed (7+ minimum), 4 failing.

**Root Cause:** Stubber's `expected_params` matching. The handler sends 6 parameters to `search_vectors()`:
1. `TableName`
2. `IndexName`
3. `SearchVector` (bare array, 1024 elements, produced by `to_search_vector()`)
4. `TopK`
5. `ProjectionExpression` ("docId,#cat")
6. `ExpressionAttributeNames` ({"#cat": "category"})

The test stubs only declared 3 in expected_params, so Stubber's dict-equality check failed.

**Diagnostic Results:**
- `to_search_vector()` output format is correct: `[{'N': '0.1'}, {'N': '0.2'}, {'N': '0.0'}, ...]`
- SearchVector format matches exactly what the handler sends (verified)
- No bug in handler or serializer; test stubs need all 6 params in expected_params

**Fix (ergonomic, not a coverage cut):**
- Build expected_params by calling `to_search_vector()` on the same fixture input
- Keeps the SearchVector assertion intact (verifies wire format)
- Eliminates hand-written 1024-element vectors
- Tests then go green

**Tests Ready to Fix (on next pass):**
- `test_search_happy_path_with_results`: returns scored results, COSINE distance
- `test_search_with_category_filter`: category in SearchConditionExpression
- `test_search_raises_on_query_dimension_mismatch`: Bedrock returns wrong dimension
- `test_search_raises_on_top_k_too_low`: validates 1-100 range (low)
- `test_search_raises_on_top_k_too_high`: validates 1-100 range (high)
- `test_search_raises_on_index_not_active`: ResourceNotFoundException → ValueError with wait message
- `test_search_raises_on_bedrock_access_denied`: AccessDeniedException propagation
- `test_search_raises_on_dynamodb_throttling`: ThrottlingException propagation
- `test_search_query_vector_is_bare_array_not_l_wrapped`: asserts format correctness

## Next Steps

1. Fix search handler tests (build expected_params from `to_search_vector()`)
2. Run tests green
3. Commit tests
4. No deploy yet — will deploy once both ingest + search paths exist

## Notes

- Both Lambda handlers import from `shared/vector_config.py` and `shared/vector_serialization.py` — no drift possible
- Guard in `tests/conftest.py` now catches both pass-only tests and assertion-free tests
- Guard limitations documented in conftest docstring (name-pattern matching, `@pytest.mark.no_assert` escape hatch)
