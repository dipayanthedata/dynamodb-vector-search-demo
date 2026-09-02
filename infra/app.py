"""CDK app for the DynamoDB native vector search demo.

One stack: base table + vector index (via custom resource) + ingest/search Lambdas.
Account and region always come from the CDK environment (CDK_DEFAULT_ACCOUNT /
CDK_DEFAULT_REGION, set by `cdk deploy` from your configured AWS credentials) -
never hardcoded, per CLAUDE.md.
"""

import os
import sys
from pathlib import Path

# Makes the repo-root `shared/` package (imported by both this CDK app and the Lambda
# handlers, so the two can't drift on shared config - see shared/vector_config.py)
# importable from here, since cdk.json runs this script with infra/ as the working
# directory, one level below the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aws_cdk as cdk
from stacks import VectorSearchStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

VectorSearchStack(app, "DynamoDBVectorSearchDemo", env=env)

cdk.Tags.of(app).add("project", "dynamodb-vector-search-demo")
cdk.Tags.of(app).add("managed-by", "cdk")

app.synth()
