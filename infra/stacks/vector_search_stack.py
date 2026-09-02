"""DynamoDB native vector search demo: base table, vector index, ingest + search Lambdas.

Built incrementally - resources are added one build-order step at a time (see
CLAUDE.md / commit history), each step verified with `cdk synth` before the next.
This step: base table + vector index custom resource. No ingest/search Lambdas yet.
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
from custom_constructs import VectorIndex


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

        # `category` (the vector index's INLINE_FILTER attribute, see docs/api-notes.md's
        # "Filtering design for this demo") is deliberately NOT declared on the table
        # above. DynamoDB's CreateTable rejects any AttributeDefinitions entry that isn't
        # referenced by the table's own key schema or a secondary index defined in the
        # same call - and TableV2 doesn't expose a way to add an unreferenced one anyway.
        # VectorIndex adds it to AttributeDefinitions in its own UpdateTable call, in the
        # same request that adds the vector index whose SearchSchema references it -
        # exactly as docs/api-notes.md section (a) documents.
        self.vector_index = VectorIndex(self, "VectorIndex", table=self.table)

        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "TableArn", value=self.table.table_arn)
        CfnOutput(self, "VectorIndexName", value=self.vector_index.index_name)
        CfnOutput(self, "VectorIndexArn", value=self.vector_index.index_arn)
