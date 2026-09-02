"""DynamoDB native vector search demo: base table, vector index, ingest + search Lambdas.

Built incrementally - resources are added one build-order step at a time (see
CLAUDE.md / commit history), each step verified with `cdk synth` before the next.
This step: the base table only. No vector index yet (added in the next step via
a custom resource - see docs/api-notes.md section (a); CloudFormation has no
native VectorIndexes property, see section (c)).
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


class VectorSearchStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # TableV2, not the legacy Table L2: it's the currently recommended DynamoDB L2
        # construct in aws-cdk-lib 2.267.0. Note it synthesizes to AWS::DynamoDB::GlobalTable
        # in the rendered template, not AWS::DynamoDB::Table, even with zero replicas
        # configured (as here) - that's just how TableV2 models the resource in CDK, not
        # something we're opting into. The vector index index is added out-of-band via a
        # custom resource calling UpdateTable (see the next build step) against the table
        # by name/ARN, entirely independent of which CDK L2 provisioned it - and a
        # zero-replica GlobalTable is architecturally just a normal single-region DynamoDB
        # table at the data-plane level DynamoDB itself operates on, so no incompatibility
        # is expected. docs/api-notes.md's vector search requirements/limitations page is
        # silent on GlobalTable specifically (it covers capacity mode, precision, FGAC,
        # pagination, Query/Scan, PartiQL, and region availability, but not this) - this is
        # a reasoned inference, not a cited fact, and gets its real confirmation in the next
        # step when the vector index custom resource's UpdateTable call actually succeeds
        # against this table.
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

        # `category` (the future vector index's INLINE_FILTER attribute, see
        # docs/api-notes.md's "Filtering design for this demo") is deliberately NOT declared
        # here. DynamoDB's CreateTable rejects any AttributeDefinitions entry that isn't
        # referenced by the table's own key schema or a secondary index defined in the same
        # call - and TableV2 doesn't expose a way to add an unreferenced one anyway. It gets
        # added to AttributeDefinitions in the next step's UpdateTable call, in the same
        # request that adds the vector index whose SearchSchema references it - exactly as
        # docs/api-notes.md section (a) documents: "If a table's AttributeDefinitions
        # doesn't already declare an attribute referenced in SearchSchema, it must be added
        # to AttributeDefinitions in the same UpdateTable call, exactly like a GSI key
        # attribute."

        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "TableArn", value=self.table.table_arn)
