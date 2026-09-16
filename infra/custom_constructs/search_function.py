"""SearchFunction: embeds a `query` via Bedrock Titan Text Embeddings V2 (same
model and dimension as ingest), then searches the vector index via SearchVectors.
Returns scored results with measured timings, interpreted per DistanceFunction.

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
    VECTOR_INDEX_NAME,
)

from .lambda_asset import stage_lambda_asset

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LAMBDA_ASSET_DIR = _REPO_ROOT / "lambda" / "search"


class SearchFunction(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: ITableV2,
        boto3_layer: LayerVersion,
    ) -> None:
        super().__init__(scope, construct_id)

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
        # SearchVectors is a table-level action - scoped to the table ARN.
        role.add_to_principal_policy(
            PolicyStatement(
                actions=["dynamodb:SearchVectors"],
                resources=[table.table_arn],
            )
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
                "VECTOR_INDEX_NAME": VECTOR_INDEX_NAME,
                "EMBEDDING_MODEL_ID": EMBEDDING_MODEL_ID,
                "EMBEDDING_DIMENSIONS": str(EMBEDDING_DIMENSIONS),
                "EMBEDDING_NORMALIZE": str(EMBEDDING_NORMALIZE).lower(),
            },
            timeout=Duration.seconds(30),
            log_group=log_group,
            role=role,
        )

    def _bare_lambda_role(self, log_group: LogGroup) -> Role:
        role = Role(self, "Role", assumed_by=ServicePrincipal("lambda.amazonaws.com"))
        role.add_to_principal_policy(
            PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[log_group.log_group_arn, f"{log_group.log_group_arn}:*"],
            )
        )
        return role
