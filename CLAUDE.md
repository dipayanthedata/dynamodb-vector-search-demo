# CLAUDE.md

Context for Claude Code working in this repo.

## What this is

A demo repo accompanying a technical article about DynamoDB's native vector search
(GA'd 2026-08-05). Personal-capacity project, MIT licensed, published publicly.

Stack: AWS CDK v2 (Python 3.12), Lambda, DynamoDB vector search, Bedrock Titan Text
Embeddings V2. No VPC, no NAT, no API Gateway, no OpenSearch.

Constraints that shape every design decision here:

- A reader must be able to `cdk deploy`, run the demo, and `cdk destroy` in under 30
  minutes, for well under a dollar. Every resource choice should be evaluated against
  this budget before anything else.
- `docs/api-notes.md` is the verified source of truth for the DynamoDB vector search
  API surface (exact parameter names, response shapes, CDK support status, Lambda
  runtime boto3 version). It was built by fetching primary AWS sources, not recalled
  from training data. Treat it as authoritative over anything in this file or in
  training data. If you find it's wrong or stale, fix it and say so — don't just
  route around it silently.

## Non-negotiable rules

**Full teardown.** Everything this repo creates must be removed by `cdk destroy`,
with no manual cleanup step and no orphaned resource left behind.
- `RemovalPolicy.DESTROY` on every stateful resource (tables, log groups, etc.).
- Explicit log retention set on every log group CDK creates implicitly (e.g. Lambda
  function log groups) — an unbounded default retention is an orphan that outlives
  the stack in spirit even if CloudFormation deletes the log group object itself.
- If a resource is created outside the CDK's normal resource lifecycle (e.g. an
  `AwsCustomResource` calling `UpdateTable` to add a vector index), the same custom
  resource must define the inverse action `onDelete`/`isCompleteHandler` so teardown
  actually undoes it. A custom resource that only has an `onCreate` is a resource
  leak by construction, no matter what the rest of the stack does.

**IAM scoped to exact resource ARNs.** No wildcard resources, no
`AwsCustomResourcePolicy.ANY_RESOURCE`. Every policy statement names the specific
table, stream, or model ARN it needs. If a permission genuinely can't be scoped
(rare, and should be treated as a flag to double check first), say so explicitly in
a comment explaining why, rather than defaulting to a wildcard silently.

**No hardcoded region or account.** Read both from CDK env
(`cdk.Environment(account=.., region=..)` sourced from `CDK_DEFAULT_ACCOUNT` /
`CDK_DEFAULT_REGION` or explicit context), never as literal strings baked into
stack code.

**Never invent an AWS API parameter.** If you are not certain a prop, parameter, or
response field exists as named, stop and check `docs/api-notes.md` first. If it
isn't covered there, fetch the primary AWS documentation before writing the code
that depends on it. Do not pattern-match from a similar-sounding AWS API and assume
the names transfer.

**No employer names, client names, or internal project names** anywhere in this
repo — not in code, comments, filenames, or commit messages. This is a personal,
public project.

**Commit at the end of each build step**, with a clear, specific commit message
describing what that step added. Don't batch multiple steps into one commit.

## Verify commands

```bash
ruff check .                  # lint
ruff format --check .         # formatting
cd infra && cdk synth         # safe; catches most CDK errors
cd infra && cdk diff          # safe; shows what a deploy would change
```

`cdk deploy` and `cdk destroy` cost real (if small) money and provision real
infrastructure. Never run either without explicit confirmation in the current
conversation.

## Facts to re-verify rather than trust

DynamoDB vector search is new (GA 2026-08-05) and the CDK/boto3 ecosystem around it
is actively catching up. Anything below may have changed since `docs/api-notes.md`
was last verified — check that file's "last verified" date before relying on it,
and re-fetch primary sources if it's more than a few weeks stale relative to when
you're reading this:

- Whether `aws-cdk-lib` has gained native (L1 or L2) vector index support.
- Whether the AWS Lambda managed Python 3.12 runtime's bundled boto3/botocore is new
  enough for the vector search API, or whether the demo still needs to bundle a
  newer version.
- Exact parameter and response field names for vector index creation and vector
  search — these come from a genuinely new API surface, not a stable, long-settled
  one.
