"""IngestFunction: embeds `text` via Bedrock Titan Text Embeddings V2 and writes
the resulting item (with its vector) to the base table. VectorIndex (same stack)
adds the vector index on this same table separately, so any item this function
writes becomes searchable once that index exists and finishes building.

Invoked directly - no API Gateway (CLAUDE.md's no-API-Gateway constraint) - e.g. by
a script in a later build step.
"""

from pathlib import Path

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk.aws_dynamodb import ITableV2
from aws_cdk.aws_iam import PolicyStatement, Role, ServicePrincipal
from aws_cdk.aws_lambda import Code, Function, LayerVersion, Runtime
from aws_cdk.aws_logs import LogGroup, RetentionDays
from constructs import Construct

from shared.vector_config import (
    CATEGORY_ATTRIBUTE_NAME,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    EMBEDDING_NORMALIZE,
    VECTOR_ATTRIBUTE_NAME,
)

from .lambda_asset import stage_lambda_asset

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LAMBDA_ASSET_DIR = _REPO_ROOT / "lambda" / "ingest"


class IngestFunction(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: ITableV2,
        boto3_layer: LayerVersion,
    ) -> None:
        super().__init__(scope, construct_id)

        # Bedrock foundation-model ARNs are account-agnostic (double colon where an
        # account ID would otherwise go) - confirmed from AWS's own identity-based
        # policy examples for Bedrock (deny-inference example:
        # "arn:aws:bedrock:*::foundation-model/{{model-id}}"). Partition and region
        # still come from the stack's own CDK env, never hardcoded (CLAUDE.md).
        stack = Stack.of(self)
        model_arn = (
            f"arn:{stack.partition}:bedrock:{stack.region}"
            f"::foundation-model/{EMBEDDING_MODEL_ID}"
        )

        log_group = LogGroup(
            self,
            "Logs",
            retention=RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        role = self._bare_lambda_role(log_group)
        # PutItem is a table-level action - scoped to the table ARN, not the vector
        # index ARN (the index has no separate write action of its own; DynamoDB
        # populates it from base-table writes).
        role.add_to_principal_policy(
            PolicyStatement(actions=["dynamodb:PutItem"], resources=[table.table_arn])
        )
        role.add_to_principal_policy(
            PolicyStatement(actions=["bedrock:InvokeModel"], resources=[model_arn])
        )

        self.function = Function(
            self,
            "Function",
            runtime=Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=Code.from_asset(stage_lambda_asset(_LAMBDA_ASSET_DIR, ["shared"])),
            layers=[boto3_layer],
            environment={
                "TABLE_NAME": table.table_name,
                "VECTOR_ATTRIBUTE_NAME": VECTOR_ATTRIBUTE_NAME,
                "CATEGORY_ATTRIBUTE_NAME": CATEGORY_ATTRIBUTE_NAME,
                "EMBEDDING_MODEL_ID": EMBEDDING_MODEL_ID,
                "EMBEDDING_DIMENSIONS": str(EMBEDDING_DIMENSIONS),
                "EMBEDDING_NORMALIZE": str(EMBEDDING_NORMALIZE).lower(),
            },
            timeout=Duration.seconds(30),
            log_group=log_group,
            role=role,
        )

    def _bare_lambda_role(self, log_group: LogGroup) -> Role:
        # Same reasoning as VectorIndex's own _bare_lambda_role: Function's default
        # auto-created role attaches the AWS-managed AWSLambdaBasicExecutionRole
        # policy even with an explicit log_group given, which is broader than this
        # repo's "IAM scoped to exact resource ARNs" rule intends. Building the role
        # ourselves instead - no managed policies, only a log-write statement scoped
        # to this function's own specific log group.
        role = Role(self, "Role", assumed_by=ServicePrincipal("lambda.amazonaws.com"))
        role.add_to_principal_policy(
            PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[log_group.log_group_arn, f"{log_group.log_group_arn}:*"],
            )
        )
        return role
