"""CDK app for the DynamoDB native vector search demo.

One stack: base table + vector index (via custom resource) + ingest/search Lambdas.
Account and region always come from the CDK environment (CDK_DEFAULT_ACCOUNT /
CDK_DEFAULT_REGION, set by `cdk deploy` from your configured AWS credentials) -
never hardcoded, per CLAUDE.md.
"""

import os

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
