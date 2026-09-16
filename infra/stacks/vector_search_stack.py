"""DynamoDB native vector search demo: base table, vector index, ingest + search Lambdas.

Stack synthesizes to CloudFormation with:
- TableV2 (AWS::DynamoDB::GlobalTable): base table with docId partition key, on-demand billing
- VectorIndex custom resource: adds vector index with Bedrock embedding layer via UpdateTable
- IngestFunction Lambda: embeds documents and writes items to table
- SearchFunction Lambda: embeds queries and searches vector index via SearchVectors API

All resources use RemovalPolicy.DESTROY for full `cdk destroy` cleanup (CLAUDE.md).
Vector index creation happens asynchronously during stack deployment (takes ~8-10 minutes).
"""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk.aws_dynamodb import (
    Attribute,
    AttributeType,
    Billing,
    PointInTimeRecoverySpecification,
    TableEncryptionV2,
    TableV2,
)
from constructs import Construct
from custom_constructs import (
    IngestFunction,
    SearchFunction,
    VectorIndex,
    build_boto3_layer,
)


class VectorSearchStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # TableV2, not the legacy Table L2: it's the currently recommended DynamoDB L2
        # construct in aws-cdk-lib 2.267.0. Note it synthesizes to AWS::DynamoDB::GlobalTable
        # in the rendered template, not AWS::DynamoDB::Table, even with zero replicas
        # configured (as here) - that's just how TableV2 models the resource in CDK, not
        # something we're opting into.
        #
        # The open question this raises is control-plane, not data-plane: does
        # UpdateTable accept a VectorIndexUpdates request against a table whose
        # CloudFormation resource type is AWS::DynamoDB::GlobalTable? That's genuinely
        # untested - docs/api-notes.md's vector search requirements/limitations page is
        # silent on GlobalTable specifically (it covers capacity mode, precision, FGAC,
        # pagination, Query/Scan, PartiQL, and region availability, but not this). Whether
        # a zero-replica GlobalTable and a plain Table are the same DynamoDB table at the
        # data-plane level isn't in doubt - they are, by construction, since a global table
        # with zero additional replica regions is just a normal regional table underneath.
        # The vector index construct in the next step calls UpdateTable's VectorIndexUpdates
        # against this table's name/ARN; if that specific control-plane call rejects a
        # GlobalTable-backed table, stop and fall back to the legacy Table L2 rather than
        # debugging around it - see that construct's own comments for the decision point,
        # and docs/api-notes.md for whichever result actually happened.
        self.table = TableV2(
            self,
            "Table",
            partition_key=Attribute(name="docId", type=AttributeType.STRING),
            # Vector indexes require on-demand capacity mode and require the base table to
            # also be on-demand - not a cost preference, a hard requirement (docs/api-notes.md,
            # fact #4: "Vector indexes use on-demand capacity mode only and they require a
            # table that also uses on-demand capacity mode. You cannot mix the two capacity
            # modes."). Billing.on_demand() is TableV2's on-demand/PAY_PER_REQUEST mode.
            billing=Billing.on_demand(),
            # Deliberately no `dynamo_stream` - ingest is a synchronous embed-then-PutItem
            # Lambda (no async fan-out step needs a stream), and TableV2's own default is
            # "streams are disabled ... if this property is not specified", so omitting it
            # is the explicit choice, not an oversight.
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery_specification=PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=False,
            ),
            # AWS-owned key (free) rather than a customer-managed KMS key - TableV2's own
            # default, made explicit here rather than relied upon silently.
            encryption=TableEncryptionV2.dynamo_owned_key(),
        )

        # Built once and shared by every Lambda in this stack that needs a boto3 newer
        # than the managed runtime's own bundled version (docs/api-notes.md section
        # (d)) - one CloudFormation LayerVersion resource, not one per function.
        self.boto3_layer = build_boto3_layer(self, "Boto3Layer")

        # `category` (the vector index's INLINE_FILTER attribute, see docs/api-notes.md's
        # "Filtering design for this demo") is deliberately NOT declared on the table
        # above. DynamoDB's CreateTable rejects any AttributeDefinitions entry that isn't
        # referenced by the table's own key schema or a secondary index defined in the
        # same call - and TableV2 doesn't expose a way to add an unreferenced one anyway.
        # VectorIndex adds it to AttributeDefinitions in its own UpdateTable call, in the
        # same request that adds the vector index whose SearchSchema references it -
        # exactly as docs/api-notes.md section (a) documents.
        self.vector_index = VectorIndex(
            self, "VectorIndex", table=self.table, boto3_layer=self.boto3_layer
        )

        self.ingest_function = IngestFunction(
            self, "IngestFunction", table=self.table, boto3_layer=self.boto3_layer
        )

        self.search_function = SearchFunction(
            self, "SearchFunction", table=self.table, boto3_layer=self.boto3_layer
        )

        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "TableArn", value=self.table.table_arn)
        CfnOutput(self, "VectorIndexName", value=self.vector_index.index_name)
        CfnOutput(self, "VectorIndexArn", value=self.vector_index.index_arn)
        CfnOutput(
            self,
            "IngestFunctionName",
            value=self.ingest_function.function.function_name,
        )
        CfnOutput(
            self,
            "SearchFunctionName",
            value=self.search_function.function.function_name,
        )
