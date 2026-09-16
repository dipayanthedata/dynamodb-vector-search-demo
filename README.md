# DynamoDB Native Vector Search + Bedrock Titan Embeddings Demo

A hands-on demo accompanying a technical article about DynamoDB's native vector search (GA'd 2026-08-05). Shows semantic similarity search side-by-side with a keyword baseline, all running on a shoestring budget in under 30 minutes.

**Stack:** AWS CDK v2 (Python 3.12), Lambda, DynamoDB vector search, Bedrock Titan Text Embeddings V2.

## Quickstart

### Prerequisites
- Python 3.12+
- `pip` (vendored with Python)
- AWS CLI and credentials configured (personal AWS account, not work)
- ~$1 budget (demo resources are on-demand, short-lived, not billed when idle)

### Deploy and run

```bash
# 1. Install dependencies (one time, or after requirements files change)
make install

# 2. Verify code quality
make lint

# 3. Run the test suite
make test

# 4. Preview the CloudFormation template (safe, no resources created)
make diff

# 5. Deploy to your AWS account
cd infra && cdk deploy

# 6. Run the demo
python3 scripts/demo.py

# 7. Clean up (removes all resources)
cd infra && cdk destroy
```

### What gets deployed

- A DynamoDB table with a vector index (5 GB on-demand storage default)
- Two Lambda functions (ingest + search)
- CloudWatch log groups (auto-deleted by `cdk destroy`)
- Bedrock API calls for embeddings (pay-per-token)

**Total:** under $1 for a complete run, ~30 minutes end-to-end.

## Performance (Step 8 Results)

From a real deployment with 60-document corpus:

| Metric | Value |
|--------|-------|
| Deploy time | 652 seconds (~11 minutes) |
| Vector index backfill | 8m 53s |
| Seed (60 docs) | 26.8s (0.45s per doc) |
| Search p50 latency | 265ms (warm) |
| Search p95 latency | 307ms (warm) |
| Destroy cleanup | 94 seconds |

Cold-start Lambda (first query on empty table): 765ms  
Warm steady-state (average): 272ms  

See `docs/results.md` for full measurements and quality verification.

## What the demo does

1. **Ingest phase:** takes a corpus of short texts, generates embeddings via Bedrock Titan, stores vectors in DynamoDB
2. **Search phase:** accepts a query, generates its embedding, searches the vector index for top-K similar items
3. **Comparison:** runs the same queries against a keyword baseline (no ML) side-by-side

See `scripts/demo.py` for implementation details.

## Design decisions

Every major choice is documented:
- `CLAUDE.md` — standing rules and constraints for this repo
- `docs/api-notes.md` — verified API reference for DynamoDB vector search and Bedrock Titan, with citations to canonical AWS sources

### Why this stack?

- **Vector indexes** (not OpenSearch/Elasticsearch) — native to DynamoDB, lower ops overhead, simpler IAM
- **Titan Embeddings V2** — text-optimized, 1024-dim default, good quality/cost trade-off for short texts
- **PAY_PER_REQUEST billing** — no capacity planning, predictable costs at demo scale
- **No VPC/NAT/API Gateway** — simpler networking, faster to deploy
- **Bedrock instead of local embeddings** — managed, no LLM ops burden (this repo doesn't host models)

## Project status

- Step 1: Scaffold + CDK skeleton ✅
- Step 2: Base DynamoDB table ✅
- Step 3: Vector index custom resource ✅
- Step 4: Ingest Lambda (embedding generation + storage) ✅
- Step 5: Search Lambda (vector search + result formatting) ✅
- Step 6: Scripts + demo pipeline ✅
- Step 7: Guardrail assertions + dimension consistency ✅
- Step 8: Full deployment, scaling tests, and results ✅

## License

MIT — fork, remix, adapt freely. See LICENSE.

## Questions?

This repo is a learning resource accompanying a public article. Issues and PRs welcome.
