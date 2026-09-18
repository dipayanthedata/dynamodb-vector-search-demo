# DynamoDB Native Vector Search + Bedrock Titan Embeddings V2 — Verified API Reference

**Status: verified source-of-truth reference. Last verified 2026-09-02 (revision 2 — see "What changed in this revision" below).**

## A note on tool-result integrity

Every AWS documentation page fetched for this file (DynamoDB API Reference pages,
the DynamoDB Developer Guide, and the Bedrock User Guide — three unrelated
properties with different real authoring teams) ended with an identical,
verbatim block: a second `## See also` heading (lowercase, appearing *after* the
page's own legitimate `## See Also` section where one exists) instructing the
reader to run `aws agent-toolkit search-skills --search-query ...`. The exact
wording was byte-for-byte identical across pages with otherwise completely
different structure and content, and on the Bedrock page it appeared with no
preceding legitimate "See Also" section at all. This does not match how AWS
documentation actually varies its SDK-link sections page to page, and reads as
an injected instruction to an AI agent, not organic AWS content. It was not
executed. Flagging this in the artifact itself, not just in conversation, so
anyone reading this file later has the same warning.

## What changed in this revision (2026-09-02, second pass)

The first pass verified every claim against a single source (mostly the
DynamoDB Developer Guide's narrative "Creating and searching vector indexes"
page) and treated that page's internal consistency as confirmation. That's not
independent verification — a single mistaken or stale source would have
"confirmed" every one of its own claims. This revision re-verifies the
highest-stakes claims against the **canonical API Reference pages**
(`API_SearchVectors`, `API_SearchSchemaElement`, `API_UpdateTable`,
`API_AttributeValue`) instead of, or in addition to, the narrative guide, and
records exactly which page backs each claim below. Where the API Reference and
the Developer Guide agree, both are cited. Where only the Developer Guide
covers a behavioral detail not present in the terse API Reference schema pages
(e.g. dedicated search endpoints, silent de-indexing behavior), that is
called out explicitly as narrative-guide-only, not double-sourced.

Corrections made in this revision, per author review:
1. **Filtering design was wrong in the first pass.** Filter attributes belong
   in the vector index's `SearchSchema`, not in `Projection.INCLUDE`. See the
   corrected "Filtering design for this demo" section below.
2. **`SearchConditionExpression` equality-only claim now has a second,
   independent citation** from `API_SearchVectors` itself (see (b) below),
   not just the narrative guide.
3. Added a dedicated Bedrock Titan Text Embeddings V2 section (was out of
   scope for the first pass).
4. Recorded the exact boto3/botocore pin decision (not just the minimum).

---

## (a) Creating a vector index via `update_table`

Vector indexes are managed through the same `CreateTable` and `UpdateTable`
operations already used for tables:
- `VectorIndexes` — top-level list parameter on `CreateTable` (create table +
  vector index together)
- `VectorIndexUpdates` — top-level list parameter on `UpdateTable` (add or
  remove a vector index on an existing table)

### Exact shape of `VectorIndexUpdates` (from `API_UpdateTable`'s request syntax block, verbatim)

```json
"VectorIndexUpdates": [
    {
        "Create": {
            "Dimensions": {{number}},
            "DistanceFunction": "{{string}}",
            "IndexName": "{{string}}",
            "Projection": {
                "NonKeyAttributes": [ "{{string}}" ],
                "ProjectionType": "{{string}}"
            },
            "SearchSchema": [
                {
                    "AttributeName": "{{string}}",
                    "SearchSchemaElementType": "{{string}}"
                }
            ],
            "VectorAttribute": {
                "AttributeName": "{{string}}"
            }
        },
        "Delete": {
            "IndexName": "{{string}}"
        }
    }
]
```

`API_UpdateTable`'s prose, quoted verbatim: *"A list of vector indexes to be
added to or removed from the table. You can add or remove one vector index for
each `UpdateTable` operation. To add a vector index, specify `IndexName`,
`VectorAttribute`, `Dimensions`, `DistanceFunction`, and `Projection`. To
remove a vector index, specify only the `IndexName`."*

Key points:
- **One vector index create/delete per `UpdateTable` call.** A call with two
  `Create` entries fails with `LimitExceededException`. This limit is shared
  with GSI creation on the same table (confirmed by the DynamoDB Developer
  Guide's working-with page: *"You can create or delete only one vector index
  per table at a time. This limit is shared with global secondary index
  creation on the same table... A second `UpdateTable` request that creates or
  deletes an index while another index operation is in progress fails with
  `LimitExceededException: Subscriber limit exceeded: Only 1 online index can
  be created or deleted simultaneously per table.`"*). A single `UpdateTable`
  call with two `Create` actions fails with the identical error.
- `DistanceFunction` valid values: `COSINE | DOT_PRODUCT | EUCLIDEAN` (from the
  `HarnessBedrockModelConfig`-equivalent enum on the vector index `Create`
  shape — confirmed identically in the response's `VectorIndexes[].
  DistanceFunction` field in `API_UpdateTable`'s response syntax).
- `Dimensions`: integer, 1–4096 (see Quotas table below).
- `SearchSchema` is `Array of SearchSchemaElement objects` — see (b) below for
  its exact shape and the `HASH` vs `INLINE_FILTER` distinction, which is the
  part that was wrong in the first pass of this document.
- If a table's `AttributeDefinitions` doesn't already declare an attribute
  referenced in `SearchSchema`, it must be added to `AttributeDefinitions` in
  the same `UpdateTable` call, exactly like a GSI key attribute.
- A `CreateTable` request can define multiple vector indexes at once (no
  one-at-a-time restriction there), up to the per-table limit of 5.

Citations:
- `API_UpdateTable` (canonical API Reference) — https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_UpdateTable.html — fetched 2026-09-02. Backs: exact `VectorIndexUpdates` shape, one-parameter-per-nested-object structure, response `TableDescription.VectorIndexes[]` shape.
- DynamoDB Developer Guide, "Creating and searching vector indexes" — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearchWorkingWith.html — fetched 2026-09-02. Backs: the one-at-a-time limit's exact error message/text (not present in the terse API Reference page), worked CLI examples.

### Index build progress (`DescribeTable` / the `UpdateTable` response's `TableDescription.VectorIndexes[]`)

Both `UpdateTable`'s own response and `DescribeTable` report, per vector index:
- `IndexStatus`: `CREATING` → `ACTIVE`. **There is no `BACKFILLING` status value.**
- `Backfilling`: boolean, `true` while DynamoDB populates the index from
  existing base table data.

`SearchVectors` returns `ValidationException` while `Backfilling` is `true`,
and can still return it briefly after `IndexStatus` first reports `ACTIVE`,
because `SearchVectors` is served by a **separate search endpoint** from the
one that serves `DescribeTable`/`UpdateTable` (see (b) below) — that endpoint
can lag the management-plane status. Narrative guide, quoted verbatim: *"For a
readiness check that does not depend on either status field, issue a real
`SearchVectors` request in a retry loop. Treat the first successful response
as the signal that the index is ready."* This is a Developer-Guide-only
behavioral detail — the terse API Reference pages for `UpdateTable`/
`DescribeTable` don't narrate readiness semantics, only the raw fields.

Citation: DynamoDB Developer Guide, "Creating and searching vector indexes" — same URL as above — fetched 2026-09-02.

---

## (b) `search_vectors` — request and response shape

Confirmed **independently from two canonical API Reference pages** (not just
the narrative guide) that the boto3 client method is `search_vectors` (API
operation `SearchVectors`), and that it is a genuinely new operation — vector
indexes do not support `Query`, `Scan`, or PartiQL.

### Request syntax (from `API_SearchVectors`, verbatim JSON block)

```json
{
   "ExpressionAttributeNames": { "{{string}}": "{{string}}" },
   "ExpressionAttributeValues": { "{{string}}": { "AttributeValue": "..." } },
   "IndexName": "{{string}}",
   "ProjectionExpression": "{{string}}",
   "ReturnConsumedCapacity": "{{string}}",
   "SearchConditionExpression": "{{string}}",
   "SearchVector": [ { "AttributeValue": "..." } ],
   "TableName": "{{string}}",
   "TopK": {{number}}
}
```

Per-parameter, quoted from `API_SearchVectors`'s Request Parameters section:

- **`IndexName`** (required) — *"The name of the vector index to search. The
  index must be in the `ACTIVE` state."* String, 3–255 chars.
- **`SearchVector`** (required) — *"The search vector to compare against the
  indexed vectors. Each element is a 32-bit IEEE-754 floating point number,
  provided in DynamoDB list format... The number of dimensions must match the
  number of dimensions configured for the vector index."* Type: **Array of
  `AttributeValue` objects**, 1–4096 items.
- **`TableName`** (required) — name or ARN of the table.
- **`TopK`** (required) — *"The number of most similar results to return.
  Valid values range from 1 to 100, inclusive."* **This is a hard service-side
  cap — the demo must validate `TopK <= 100` client-side and fail with a clear
  error rather than let the service reject it.**
- **`SearchConditionExpression`** (optional) — *"A condition expression used
  to filter the vector search results. The expression can reference attributes
  defined in the vector index search schema, including `HASH` and
  `INLINE_FILTER` key elements. The `HASH` and `INLINE_FILTER` attributes
  support only the equality operator (`=`). You can reference only top-level
  attributes from the search schema."* — **This directly answers the open
  question: confirmed, only `=`, from the canonical API Reference itself, not
  just the narrative guide.** (The narrative guide independently says the same
  thing: *"The equality operator (`=`) is supported in `SearchConditionExpression`
  for both vector index partition key and inline filter attributes. Comparison,
  range, and set-membership operators (`<>`, `<`, `<=`, `>`, `>=`, `IN`) are not
  yet available."* Two independent pages, same answer.)
- `ExpressionAttributeNames` / `ExpressionAttributeValues` — standard DynamoDB
  expression substitution maps, optional.
- `ProjectionExpression` (optional) — *"identifies one or more attributes to
  retrieve from the index... Only attributes projected into the vector index
  can be retrieved."*
- `ReturnConsumedCapacity` (optional) — `INDEXES | TOTAL | NONE`.

### Response syntax (from `API_SearchVectors`, verbatim JSON block)

```json
{
   "ConsumedCapacity": {
      "VectorSearchRequestBytes": number,
      "VectorWriteRequestBytes": number
   },
   "SearchResults": [
      {
         "Item": { "string": { "AttributeValue": "..." } },
         "Score": number
      }
   ]
}
```

- `SearchResults` — *"A list of items returned by the vector similarity
  search, sorted by similarity with the most similar item first."*
- Each result: `Item` (projected attributes) + `Score` (float).

### Score direction — confirmed directly from `API_SearchVectors`'s own description (not the narrative guide's summary of it)

Quoted verbatim, this is the canonical statement, not a paraphrase:

> Score interpretation depends on the distance function:
> - `COSINE` - Returns the items with the *k smallest* scores. Scores range
>   from 0 (identical) to 2 (opposite). Lower scores indicate higher similarity.
> - `EUCLIDEAN` - Returns the items with the *k smallest* scores. Scores
>   represent the Euclidean distance between vectors. Lower scores indicate
>   higher similarity.
> - `DOT_PRODUCT` - Returns the items with the *k highest* scores. Higher
>   scores indicate higher similarity.

**Implementation note:** this must be encoded as a per-`DistanceFunction`
lookup (e.g. `{"COSINE": "asc", "EUCLIDEAN": "asc", "DOT_PRODUCT": "desc"}` or
equivalent), not a hardcoded sort direction — `SearchVectors` already returns
results pre-sorted correctly by the service, so application code should never
need to re-sort, but any code that *interprets* a `Score` value (e.g. a
similarity-threshold check, or a test asserting "smaller is better") must key
off `DistanceFunction`, not assume one direction.

### `AttributeValue` — the L/N vs. plain-array asymmetry, confirmed from `API_AttributeValue`

`API_AttributeValue`, quoted verbatim:
- **`L`** — *"An attribute of type List. For example: `"L": [ {"S": "Cookies"},
  {"S": "Coffee"}, {"N": "3.14159"}]`. Type: Array of `AttributeValue` objects."*
- **`N`** — *"An attribute of type Number. For example: `"N": "123.45"`.
  Numbers are sent across the network to DynamoDB as strings... Type: String."*

Cross-referencing this with `API_SearchVectors`'s own parameter types:
- **Stored item attribute** (written via `PutItem`/`UpdateItem`/
  `BatchWriteItem`): the vector lives in an item attribute whose type is `L`
  (List), each element an `AttributeValue` with `N` set — i.e. the wire shape
  is `{"L": [{"N": "0.1234"}, {"N": "-0.5678"}, ...]}`.
- **`SearchVector` request parameter**: typed as `Array of AttributeValue
  objects` directly — **not** `L` containing that array. The wire shape is
  `[{"N": "0.1234"}, {"N": "-0.5678"}, ...]`, with no outer `L` wrapper.

This is a real asymmetry between how a vector is written (wrapped in `L`) and
how it's passed to search (bare array), both using the same `AttributeValue`
building block underneath. Confirmed identically by the Developer Guide's own
explicit callout: *"**SearchVector is a plain list, not a DynamoDB L type.**
The `SearchVector` request parameter is a plain JSON array of number objects
(`[{"N": "0.1234"}, ...]`). Do not wrap it in a DynamoDB `L` type as you would
when storing a vector in an item attribute."*

**Implementation consequence (per author's build-order correction #2):** both
directions of this serialization must live in **one shared module** imported
by both the ingest Lambda (writes, needs the `L` wrapper) and the search
Lambda (queries, needs the bare array) — e.g. `to_stored_vector(floats) ->
list[dict]` (produces the `L`-wrapped shape as the actual item attribute
value) and `to_search_vector(floats) -> list[dict]` (produces the bare
`N`-dict array for the `SearchVector` parameter), plus a round-trip unit test
(`to_search_vector(floats)` should equal the inner list of
`to_stored_vector(floats)["L"]`) so the two functions cannot silently drift
apart.

Citations:
- `API_SearchVectors` (canonical API Reference) — https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_SearchVectors.html — fetched 2026-09-02. Backs: full request/response shape, `TopK` range, `SearchConditionExpression` equality-only statement, score direction per distance function, `SearchVector` typed as bare `AttributeValue` array.
- `API_AttributeValue` (canonical API Reference) — https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_AttributeValue.html — fetched 2026-09-02. Backs: `L` and `N` member definitions, confirming the asymmetry above.
- DynamoDB Developer Guide, "Creating and searching vector indexes" — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearchWorkingWith.html — fetched 2026-09-02. Backs (narrative-guide-only, not in the terse API Reference pages): dedicated search endpoints, silent de-indexing on missing partition key, stale-embedding behavior, "SearchVector is a plain list" explicit callout, eventual-consistency note on writes.

### Behavioral details only documented in the narrative guide (not in the terse API Reference schema pages)

- **Dedicated endpoints.** *"`SearchVectors` requests use dedicated
  vector-search endpoints, which are distinct from the standard DynamoDB
  endpoints... The AWS SDKs and AWS CLI route `SearchVectors` requests to the
  correct endpoint automatically."* Endpoint patterns for a raw HTTP client:
  `{account-id}.search-ddb.{region}.amazonaws.com` or dual-stack
  `search-dynamodb.{region}.api.aws`. No CDK/networking implication for this
  demo — boto3 handles it.
- **`dynamodb:SearchVectors` is a separate IAM action**, and FGAC condition
  keys (`dynamodb:LeadingKeys`) do **not** apply to it — cannot scope by
  partition-key value at the IAM layer. Resource ARN format:
  `arn:aws:dynamodb:{region}:{account-id}:table/{table-name}/index/{index-name}`.
- **Missing partition key → silent de-indexing.** If the index's `SearchSchema`
  defines a `HASH` and an item is written without that attribute, the base
  table write succeeds but the item is silently excluded from the vector
  index — no error, and it never appears in `SearchVectors` results.
- **Stale embeddings are not recomputed.** DynamoDB does not regenerate
  embeddings; editing source text without rewriting the vector leaves the
  index searching against the old, stale vector.
- **No pagination**; response capped at 16 MB.
- **Not supported through DAX.**
- Vector attributes are excluded from `SearchResults` by default; must be
  requested explicitly via `ProjectionExpression`, and only if projected into
  the index.
- Vector values with precision higher than 32-bit float are accepted on write
  but lose precision when replicated into the index.
- Writes are eventually consistent into the vector index (brief delay between
  a write and its appearance in `SearchVectors` results).

### Numeric quotas

| Quota | Value | Adjustable |
|---|---|---|
| Vector indexes per table | 5 | Yes (AWS Support) |
| Maximum dimensions per vector index | 4,096 | No |
| Maximum `TopK` per `SearchVectors` request | 100 | No |
| Maximum partition keys (`HASH`) per vector index | 1 | No |
| Vector search rate per partition key | 1 GBps | Yes (AWS Support) |
| Vector index write rate per partition key | 10 MBps | Yes (AWS Support) |
| Inline filters per vector index | 18 | No |
| Max base table size for vector index creation without allowlisting | 600 GB | Yes (AWS Support) |
| Concurrent vector index creations/deletions per table | 1 | No |

Citation: DynamoDB Developer Guide, "Quotas in Amazon DynamoDB" — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ServiceQuotas.html — fetched 2026-09-02.

---

## Filtering design for this demo (corrected)

**First-pass error:** the original draft of this document put the filter
attribute in `Projection.INCLUDE`. That's wrong — `Projection` only controls
which attributes are *returned* in search results, not which attributes can be
*filtered on*. Filtering is controlled entirely by `SearchSchema`.

### `SearchSchemaElement`, verbatim from `API_SearchSchemaElement`

```json
{
   "AttributeName": "{{string}}",     // required
   "SearchSchemaElementType": "{{string}}"   // required, HASH | INLINE_FILTER
}
```

> - `HASH` - *"A partition key that partitions the vector index for
>   independent scaling. When specified, you must provide this attribute's
>   value in the `SearchConditionExpression`."*
> - `INLINE_FILTER` - *"An attribute projected into the vector index for
>   filtering at the storage layer during search. Inline filters are optional
>   in the `SearchConditionExpression`."*

This confirms the author's correction precisely: `HASH` makes the attribute's
value **mandatory** on every search (the demo does not want this — it would
force every search to specify a category, hiding the unfiltered case). `INLINE_FILTER` makes filtering
**optional** — exactly the behavior needed to demonstrate both an unfiltered
similarity search and a filtered one side by side.

**Decision for this demo:** the vector index's `SearchSchema` defines exactly
one element:
```json
[{"AttributeName": "category", "SearchSchemaElementType": "INLINE_FILTER"}]
```
No `HASH` element. `category` must also be added to the table's
`AttributeDefinitions` in the same `UpdateTable` call (per (a) above).

Citation: `API_SearchSchemaElement` (canonical API Reference) — https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_SearchSchemaElement.html — fetched 2026-09-02.

---

## (c) Does `aws-cdk-lib` have native vector index support?

**No — not merged, in either the L1 (`CfnTable`/`CfnGlobalTable`) or L2
(`Table`/`TableV2`) constructs, as of the latest checked release.**

- Latest `aws-cdk-lib` release checked: **v2.267.0**, released 2026-08-27
  (confirmed via `gh release list --repo aws/aws-cdk`, fetched 2026-09-02).
- Work is in progress: **PR aws/aws-cdk#38577**, "feat(dynamodb): add vector
  index support to Table and TableV2," opened 2026-08-17, **state: OPEN, not
  merged** (checked 2026-09-02). Proposes `Table.addVectorIndex()`,
  `TableV2.vectorIndexes`/`addVectorIndex()`, and a `grantVectorSearch()`
  method (deliberately not folded into `grantReadData()`, since FGAC doesn't
  apply to `SearchVectors` — matches the finding above). The PR's own
  description states CI is red because the public CloudFormation registry
  schema for `AWS::DynamoDB::Table`/`GlobalTable` had not yet modeled
  `VectorIndexes` as of authoring.
- Independently confirmed via the live CloudFormation Template Reference for
  `AWS::DynamoDB::Table` (fetched 2026-09-02): full documented property list
  is `AttributeDefinitions`, `BillingMode`, `ContributorInsightsSpecification`,
  `DeletionProtectionEnabled`, `GlobalSecondaryIndexes`,
  `ImportSourceSpecification`, `KeySchema`, `KinesisStreamSpecification`,
  `LocalSecondaryIndexes`, `OnDemandThroughput`,
  `PointInTimeRecoverySpecification`, `ProvisionedThroughput`,
  `ResourcePolicy`, `SSESpecification`, `StreamSpecification`, `TableClass`,
  `TableName`, `Tags`, `TimeToLiveSpecification`, `WarmThroughput`. **No
  `VectorIndexes` property.**

**Implication for this demo:** base table via `Table`/`TableV2`
(`PAY_PER_REQUEST`), vector index added out-of-band via a Provider-backed
custom resource calling `update_table`. Revisit if/when PR #38577 merges.

Citations:
- aws-cdk-lib GitHub releases — https://github.com/aws/aws-cdk/releases — fetched 2026-09-02 (v2.267.0, 2026-08-27)
- PR aws/aws-cdk#38577 — https://github.com/aws/aws-cdk/pull/38577 — fetched 2026-09-02 (OPEN, not merged)
- AWS CloudFormation Template Reference, `AWS::DynamoDB::Table` — https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-dynamodb-table.html — fetched 2026-09-02

### TableV2 (`AWS::DynamoDB::GlobalTable`) vs. legacy `Table` (`AWS::DynamoDB::Table`) — which one actually works with `UpdateTable`'s `VectorIndexUpdates`?

Nobody had written this down anywhere findable as of this writing, so it's recorded
here from a real, live test rather than inferred.

**`TableV2` works.** Live-tested 2026-09-02 against account `{account-id}`,
region `us-west-2`, `aws-cdk-lib` 2.267.0: a `TableV2` with zero replicas (which
renders as `AWS::DynamoDB::GlobalTable` in the synthesized template, not
`AWS::DynamoDB::Table`) accepted an `UpdateTable` call with `VectorIndexUpdates`
without any control-plane rejection. The custom resource's `update_table` call
succeeded immediately (accepted, `IndexStatus: CREATING`); the index then went
through the normal `CREATING`/`Backfilling` → `ACTIVE` lifecycle exactly as
documented for a plain table in section (a) above - nothing about being
GlobalTable-backed changed that lifecycle or its timing.

**Observed timing for an empty table** (zero items, so this is close to a lower
bound - a table with real data would backfill slower): `IndexStatus` reached
`ACTIVE` with `Backfilling` cleared, and the first `SearchVectors` probe against
the index succeeded, after **~522–537 seconds (~9 minutes)** of polling at
15-second intervals (34 polling attempts). The first ~33 polls all still saw
`CREATING`/`Backfilling`; the 34th poll both observed `ACTIVE` and had its
`SearchVectors` probe succeed on the first try - in this test, the search-endpoint
propagation delay section (a) warns about (real, but brief) didn't manifest as a
separate additional wait beyond `IndexStatus` reaching `ACTIVE`. Don't read too
much into that - it's one data point on an empty table, not a guarantee the
search-endpoint lag is always zero.

**Cold-start Lambda timing (SearchFunction, empty table):** Single invocation against
a cold SearchFunction immediately post-deploy, before any corpus loaded:
- Bedrock embedding: **438.77ms**
- DynamoDB SearchVectors: **326.46ms**
- Total: **765.23ms**

This captures cold-start (JIT compilation, endpoint initialization). Warm cached
p50 latency is expected to be substantially lower and is measured separately in
the demo's 20-run latency distribution (see scripts/demo.py results section).

**Confirmed working end to end:** the reverse direction (`UpdateTable` with a
`Delete` vector-index action) against the same `GlobalTable`-backed table also
succeeded cleanly on `cdk destroy`, with no manual cleanup needed - see the
teardown verification recorded further down as part of this same test.

**Conclusion:** no reason found to fall back to the legacy `Table` L2 for this
demo. If a future `aws-cdk-lib` release or CloudFormation schema update changes
this (e.g. via PR #38577 above), re-verify against that version rather than
assuming this result still holds indefinitely - it was true for aws-cdk-lib
2.267.0 on 2026-09-02, not asserted as permanent.

---

## (d) Is the Lambda-bundled boto3 for `python3.12` new enough for `search_vectors`?

**Minimum required: boto3 1.43.64.** Confirmed from boto3's `CHANGELOG.rst`:
an `api-change:dynamodb` entry at that version reads *"Vector indexes are a
type of index in Amazon DynamoDB that enable similarity search on vector
embedding stored in your table items..."* — lines up with the feature's GA
date of 2026-08-05.

**Lambda's bundled version cannot be pinned to a fixed number from official
docs.** AWS Lambda's own documentation: *"The version of the AWS SDK included
in the Python runtime depends on the runtime version and your AWS Region,"*
checked only via `boto3.__version__` at runtime, with no published static
table. AWS's own recommendation: *"we recommend that you always include the
SDK modules your code uses (along with any dependencies) in your function's
deployment package or in a Lambda layer."* One historical data point (not
authoritative for today): python3.12's December 2023 launch bundled
boto3/botocore 1.34.32 — many versions behind what's needed.

**Decision for this demo:** do not rely on the runtime-included boto3. Pin and
bundle explicitly:
- `boto3==1.43.87`
- `botocore==1.43.87`

(1.43.87 is the latest release as of 2026-09-02, confirmed via `pip index
versions boto3`; boto3 1.43.87's own dependency metadata requires
`botocore>=1.43.87,<1.44.0`, so pinning botocore to the same 1.43.87 satisfies
that exactly and removes any resolver ambiguity — checked via
`pypi.org/pypi/boto3/1.43.87/json`, fetched 2026-09-02.) Both comfortably
exceed the 1.43.64 minimum.

**Bundling method (per author's build-order correction #5): no Docker.** A
reader must be able to deploy on a clean machine inside a 30-minute budget, so
this demo does **not** use `PythonFunction` bundling (which requires a
container runtime, whether Docker/Finch/Podman). Instead: a Makefile target
runs `pip install boto3==1.43.87 botocore==1.43.87 -t <layer-asset-dir>`
directly on the host (requires only Python + pip, which the reader already
has to run CDK), producing one shared Lambda layer asset consumed by both the
ingest and search Lambda functions via CDK's `LayerVersion.from_asset()` /
`Code.from_asset()` pointed at that directory. This is the same
pip-install-into-a-directory mechanism CDK's own `PythonFunction` uses
internally — we're just doing it directly, without Docker, to keep the deploy
path host-only.

Citations:
- boto3 `CHANGELOG.rst` — https://raw.githubusercontent.com/boto/boto3/develop/CHANGELOG.rst — fetched 2026-09-02. Backs: 1.43.64 as the version that added vector index support.
- AWS Lambda Developer Guide, "Building Lambda functions with Python" — https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html — fetched 2026-09-02. Backs: no static bundled-SDK-version table; recommendation to bundle your own SDK.
- `pip index versions boto3` (run locally) — fetched 2026-09-02. Backs: 1.43.87 is latest.
- `https://pypi.org/pypi/boto3/1.43.87/json` (fetched locally) — fetched 2026-09-02. Backs: boto3 1.43.87 requires `botocore>=1.43.87,<1.44.0`.

---

## Bedrock Titan Text Embeddings V2 — request/response shape and dimension choice

**Model ID: `amazon.titan-embed-text-v2:0`**, invoked via the standard Bedrock
Runtime `InvokeModel` operation (not a vector-search-specific API — this part
of the stack is unrelated to the DynamoDB API surface above).

### Request body (verbatim from the Bedrock User Guide's model parameters page)

> The inputText parameter is required. The normalize and dimensions parameters
> are optional.
> - inputText – Enter text to convert to an embedding.
> - normalize – (optional) Flag indicating whether or not to normalize the
>   output embedding. Defaults to true.
> - dimensions – (optional) The number of dimensions the output embedding
>   should have. The following values are accepted: 1024 (default), 512, 256.
> - embeddingTypes – (optional) Accepts a list containing "float", "binary",
>   or both. Defaults to `float`.

```json
{
    "inputText": "string",
    "dimensions": 1024,
    "normalize": true,
    "embeddingTypes": ["float"]
}
```

### Response body (verbatim)

> - embedding – An array that represents the embedding vector of the input
>   you provided. This will always be type `float`.
> - inputTextTokenCount – The number of tokens in the input.
> - embeddingsByType – A dictionary or map of the embedding list... This field
>   will always appear, containing at least `"float"` even if `embeddingTypes`
>   wasn't specified.

```json
{
    "embedding": [0.1, 0.2, ...],
    "inputTextTokenCount": 6,
    "embeddingsByType": {"float": [0.1, 0.2, ...]}
}
```

Note: *"the `embedding` field is not in the response if the `embeddingTypes`
only contains `binary`."* This demo never requests `binary`, so `embedding`
is always present and is the field to use directly.

### Dimension choice for this demo: **1024 (the model default)**

Reasoning, recorded here per the author's requirement to pick deliberately and
state why — this becomes the single shared constant imported by both Lambdas
and the vector index's `Dimensions` parameter:
- 1024 is the documented default; deviating from a model default needs a
  reason, and there isn't a strong one here.
- Bedrock's `InvokeModel` pricing for embedding models is per input token
  processed, not per output dimension — I was **not able to independently
  confirm this from a fetched pricing page today** (the public pricing page's
  content did not render the specific Titan Embeddings V2 line item through
  the fetch), so this is stated as a reasonably-confident-but-unverified
  assumption based on how Bedrock has historically priced embedding models,
  not to the same evidentiary standard as the DynamoDB claims above. Treat as
  a to-recheck item if the article's cost breakdown depends on it.
- Regardless of the above, at this demo's corpus scale (a few dozen short
  text items), the absolute dollar difference between 256/512/1024 dimensions
  in DynamoDB vector index storage and `SearchVectors` processed-bytes billing
  is a small fraction of a cent either way — not worth optimizing against the
  well-under-$1 budget.
- 1024 dimensions gives the best retrieval quality of the three options,
  which strengthens the semantic-vs-keyword comparison
  (`scripts/keyword_baseline.py`) that's the point of the demo.

**Shared constant name (to be defined in code, not yet written):**
`EMBEDDING_DIMENSIONS = 1024`, imported by the vector index's CDK `Dimensions`
prop, the ingest Lambda's Titan `dimensions` request field, and the search
Lambda's Titan `dimensions` request field, plus a test asserting all three
agree (per build-order item 4).

Citations:
- Bedrock User Guide, "Amazon Titan Embeddings G1 - Text" (covers both G1 and
  V2 request/response tabs) — https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html — fetched 2026-09-02. Backs: exact request/response field names, dimension enum values, model ID.
- Bedrock pricing page — https://aws.amazon.com/bedrock/pricing/ — fetched 2026-09-02, **inconclusive** (see note above) — not relied upon as a confirmed fact.

---

## Teardown finding: CDK Provider framework log groups (found, then fixed)

Live-tested 2026-09-02, same deploy as the TableV2/GlobalTable test above. After
`cdk destroy` reported full success (`✅ DynamoDBVectorSearchDemo: destroyed`, no
`DELETE_FAILED`, no rollback), independently verifying with the CLI (not just
trusting CloudFormation's own report) found:

- Stack, table, both custom-resource Lambda handlers (with their explicit log
  groups), the Step Functions waiter state machine, the Lambda layer, and every
  IAM role we authored: **confirmed gone.**
- **Two CloudWatch log groups survived**, both belonging to the CDK Provider
  construct's own internal proxy Lambdas (`framework-onEvent`, `framework-isComplete`
  - the third, `framework-onTimeout`, was apparently never invoked in this run since
  the operation never actually timed out, so Lambda never auto-created a log group
  for it):
  ```
  /aws/lambda/{stack}-VectorIndexProviderframew-{hash1}
  /aws/lambda/{stack}-VectorIndexProviderframew-{hash2}
  ```
  Both had `RetentionDays: None` (never expire) and `StoredBytes: 0`.

**Root cause:** `Provider`'s internal proxy Lambdas let Lambda auto-create their
log groups implicitly on first invocation, rather than the Provider construct
declaring them as explicit `AWS::Logs::LogGroup` CloudFormation resources (the
same pattern this repo's own `VectorIndex` construct uses deliberately for its
*own* two handlers, which is exactly why those two deleted cleanly). An
implicitly-created log group has no CloudFormation record, so nothing tells
CloudFormation to delete it when the stack is destroyed. This is a structural
property of the CDK Provider framework itself - not a bug in this repo's own
`VectorIndex` construct, and not something within reach of this construct's own
`on_event`/`is_complete` handler code to fix, since the framework's proxy Lambdas
are created internally by `Provider`, not by us.

**Deleted manually** (CLI `logs delete-log-group`) as part of this same test, and
confirmed gone by a follow-up `describe-log-groups` call.

**Fixed** in `infra/custom_constructs/vector_index.py`: `Provider` accepts a
`log_group` constructor prop - passing it an explicitly-declared `LogGroup`
(`RetentionDays.ONE_WEEK`, `RemovalPolicy.DESTROY`) wires **all three** internal
proxy Lambdas (`framework-onEvent`, `framework-isComplete`, and `framework-onTimeout`
too, closing the same gap for the one proxy this test run happened not to invoke)
to that one stack-managed log group via each proxy's own `LoggingConfig.LogGroup`,
rather than leaving any of them to auto-create their own. Confirmed by inspecting
the synthesized template directly (not just trusting the CDK prop's docstring):
the log group renders as a single `AWS::Logs::LogGroup` resource with
`DeletionPolicy: Delete`, and all three `framework-*` `AWS::Lambda::Function`
resources reference it by `Ref` in their `LoggingConfig`. `tests/test_template.py`
now asserts this generally (`test_no_implicit_lambda_log_groups`,
`test_all_log_groups_removal_policy_is_delete`) so any future Lambda added to this
stack - ours or a construct's internal one - is held to the same rule, not just
this one. No manual post-`cdk destroy` cleanup step should be needed on the next
live test; re-verify with `describe-log-groups` when step 8's deploy/destroy
walkthrough runs, since the fix has not yet been confirmed against a real deploy.

---

## Facts verified against research

1. **Vectors are stored in DynamoDB's existing List type, each element a Number. No new data type, no schema change.**
   ✅ Confirmed via `API_AttributeValue` (`L` type = array of `AttributeValue`; `N` type = number-as-string) plus the Developer Guide's worked example. Source: https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_AttributeValue.html — fetched 2026-09-02.

2. **Max 4096 dimensions. Distance functions: Euclidean, Cosine, Dot product.**
   ✅ Confirmed. `SearchVector` array max 4,096 items (`API_SearchVectors`). `DistanceFunction` enum `COSINE | DOT_PRODUCT | EUCLIDEAN` (`API_UpdateTable` response shape). Sources: https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_SearchVectors.html, https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_UpdateTable.html — both fetched 2026-09-02.

3. **Query API is `SearchVectors`: topK plus inline filtering on non-vector attributes.**
   ✅ Confirmed, with precision: `TopK` (1–100, required). Filtering via `SearchConditionExpression`, equality (`=`) only, against attributes declared in the index's own `SearchSchema` — not arbitrary non-vector attributes. **This "only `=`" detail is now confirmed from two independent sources**, the canonical `API_SearchVectors` reference and the narrative guide. Source: https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_SearchVectors.html — fetched 2026-09-02.

4. **Vector indexes require on-demand (PAY_PER_REQUEST) billing mode.**
   ✅ Confirmed verbatim from the Developer Guide's requirements page. `API_UpdateTable`'s `BillingMode` enum independently confirms `PAY_PER_REQUEST` is a valid top-level value (`PROVISIONED | PAY_PER_REQUEST`). Source: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.Requirements.md — fetched 2026-09-02.

5. **CloudFormation has NO `VectorIndexes` property — the index must be added via `UpdateTable`, not a native `Table`/`TableV2` CDK construct.**
   ✅ Confirmed for the currently published CloudFormation resource schema and `aws-cdk-lib` v2.267.0. See (c) above for the full picture, including the open unmerged PR.

6. **Index build is asynchronous; searches return nothing useful until the index is ACTIVE.**
   ✅ Confirmed, with more precision: `ACTIVE` alone is necessary but not sufficient — the separate search endpoint can still lag and return `ValidationException` briefly after. See (a) above.

7. **Vector writes, vector searches, and index storage bill separately from base table costs.**
   ✅ Confirmed. Three distinct pricing dimensions, matching the `ConsumedCapacity` response shape (`VectorSearchRequestBytes`, `VectorWriteRequestBytes`) confirmed directly in `API_SearchVectors`'s response syntax. Source: https://aws.amazon.com/dynamodb/pricing/ — fetched 2026-09-02 (pricing-page prose) + https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_SearchVectors.html — fetched 2026-09-02 (response shape).

---

## Behaviors documented in this repo but NOT yet independently verified (pending step 8 live deploy)

The following behaviors are inferred from API documentation and implemented based on
that inference, but have not been confirmed against real AWS API calls in this repo's
deployed environment. Step 8's live deploy/demo will exercise them for real; until then,
treat them as provisional:

### SearchVectors exception behavior when index is not ACTIVE (section (a))

**Documented:** `SearchVectors` returns `ValidationException` while the index is
`Backfilling`, and can still return it briefly even after `DescribeTable` reports
`IndexStatus: ACTIVE`, because the search endpoint lags the management plane.

**Implemented in this repo:** `lambda/search/handler.py` catches `ValidationException`
and translates it to a `ValueError` with a user-friendly "not yet ready, retry in a
moment" message. Separately, it catches `ResourceNotFoundException` (for missing table
or index) and translates that to a distinct "not found, check table/index names"
message.

**Test stubs:** `tests/test_search_handler.py` includes illustrative stubs for both
exception paths with placeholder error messages marked as unverified. Capture attempts
during step 8 deploy:
- **Attempt 1 (deploy 1):** Missed — IAM permissions on SearchFunction were incorrect
  (used table ARN instead of index ARN), causing AccessDeniedException instead of the
  ValidationException during backfill. Fixed in step 6 commit cbff7e1.
- **Attempt 2 (redeploy post-fix):** Missed — index backfill completed before search
  polling started (timing window ~9 minutes, started polling ~10 minutes post-deploy).
  
The actual ValidationException behavior remains unverified. Handler's exception handling
(lines 146-154 in lambda/search/handler.py) is defensive and untested at this point.

**Readiness check:** The vector index custom resource's `is_complete` handler
(`lambda/vector_index_manager/handler.py` line 195–212) already probes with a real
`SearchVectors` call to verify the search endpoint is ready, which aligns with this
documented behavior. This probe will provide real-world confirmation or contradiction of
the exception behavior when step 8 runs.

To be re-visited: if step 8's real deploy shows different exception types or messages,
update `lambda/search/handler.py`, `tests/test_search_handler.py`, and this section
with the observed behavior.

---

## Observed: IndexSizeBytes Metric Lag

**Observed 2026-09-16:** After seeding a 60-document index (1024 dims, ~0.46s per doc),
the vector index `IndexSizeBytes` metric reported 0 shortly after completion, while
SearchVectors API returned live results and correct scores. DynamoDB's size metrics
update on a delayed cycle. Do not assume an index is empty based on IndexSizeBytes=0
immediately after deployment — verify with a live SearchVectors call.

---

## Resolved: CDK Provider Framework Log Groups Orphaning

**Problem (initial deployment):** Custom resources created via CDK's `Provider` framework
(e.g. the vector index custom resource) spawn Lambda functions that auto-create CloudWatch
log groups. These log groups were not declared as CDK resources and were not deleted by
`cdk destroy`, leaving them orphaned. First teardown required manual deletion of 5 log
groups (VectorIndexProviderFrameworkLogs, VectorIndexIsCompleteLogs, VectorIndexOnEventLogs,
and two others).

**Solution (confirmed 2026-09-18):** Pre-created the CDK Provider framework log groups as
explicit `aws_logs.LogGroup` CDK resources with `removal_policy=cdk.RemovalPolicy.DESTROY`.
On the 2026-09-18 teardown (118.80 seconds), all log groups deleted automatically with the
stack. No manual cleanup required. This resolved the orphaning issue completely.

**Implementation:** See `infra/stacks/vector_search_stack.py` lines with explicit LogGroup
constructs for Provider framework functions (IngestFunctionLogs, SearchFunctionLogs,
VectorIndexProviderFrameworkLogs, VectorIndexIsCompleteLogs, VectorIndexOnEventLogs).
