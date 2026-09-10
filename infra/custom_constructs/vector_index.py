"""VectorIndex: adds a DynamoDB vector index to an existing table via UpdateTable's
VectorIndexUpdates parameter (docs/api-notes.md section (a)). CloudFormation has no
native VectorIndexes property (section (c)), so this is a custom resource, not an
L1/L2 CDK construct.

Uses the CDK Provider framework, not the simpler AwsCustomResource: index creation is
asynchronous (section (a) - IndexStatus/Backfilling, plus a search-endpoint propagation
delay even after IndexStatus first reports ACTIVE), and AwsCustomResource has no
built-in wait/poll mechanism - it fires one SDK call and reports done immediately.
Provider's is_complete_handler lets us poll until the index is genuinely searchable,
and its on_event_handler's Delete branch issues the reverse UpdateTable call so
`cdk destroy` actually removes the index, not just the table.
"""

from pathlib import Path

from aws_cdk import CustomResource, Duration, RemovalPolicy
from aws_cdk.aws_dynamodb import ITableV2
from aws_cdk.aws_iam import PolicyStatement, Role, ServicePrincipal
from aws_cdk.aws_lambda import Code, Function, LayerVersion, Runtime
from aws_cdk.aws_logs import LogGroup, RetentionDays
from aws_cdk.custom_resources import Provider
from constructs import Construct

from shared.vector_config import (
    CATEGORY_ATTRIBUTE_NAME,
    DISTANCE_FUNCTION,
    EMBEDDING_DIMENSIONS,
    VECTOR_ATTRIBUTE_NAME,
    VECTOR_INDEX_NAME,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LAMBDA_ASSET_DIR = _REPO_ROOT / "lambda" / "vector_index_manager"
_LAYER_ASSET_DIR = _REPO_ROOT / "build" / "layer"


class VectorIndex(Construct):
    """One vector index on `table`, created and torn down by this construct's own
    custom resource - independent of the table's own CloudFormation lifecycle beyond
    the implicit dependency CDK infers from referencing `table.table_arn`/`table_name`.
    """

    def __init__(self, scope: Construct, construct_id: str, *, table: ITableV2) -> None:
        super().__init__(scope, construct_id)

        if not _LAYER_ASSET_DIR.exists():
            raise RuntimeError(
                f"{_LAYER_ASSET_DIR} does not exist - run `make build-layer` first "
                "(or `make synth` / `make test`, which both depend on it). This "
                "bundles a boto3/botocore new enough for search_vectors and "
                "VectorIndexUpdates without needing Docker - see "
                "docs/api-notes.md section (d)."
            )

        boto3_layer = LayerVersion(
            self,
            "Boto3Layer",
            code=Code.from_asset(str(_LAYER_ASSET_DIR)),
            compatible_runtimes=[Runtime.PYTHON_3_12],
            removal_policy=RemovalPolicy.DESTROY,
        )

        index_arn = f"{table.table_arn}/index/{VECTOR_INDEX_NAME}"

        environment = {
            "TABLE_NAME": table.table_name,
            "INDEX_NAME": VECTOR_INDEX_NAME,
            "VECTOR_ATTRIBUTE_NAME": VECTOR_ATTRIBUTE_NAME,
            "CATEGORY_ATTRIBUTE_NAME": CATEGORY_ATTRIBUTE_NAME,
            "DIMENSIONS": str(EMBEDDING_DIMENSIONS),
            "DISTANCE_FUNCTION": DISTANCE_FUNCTION,
        }

        on_event_log_group = LogGroup(
            self,
            "OnEventLogs",
            retention=RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        on_event_role = self._bare_lambda_role("OnEventHandlerRole", on_event_log_group)
        # Scoped to the table ARN only - UpdateTable is a table-level action (its
        # resource ARN is the table itself; the index doesn't exist yet on Create, and
        # is being removed, not addressed, on Delete).
        on_event_role.add_to_principal_policy(
            PolicyStatement(
                actions=["dynamodb:UpdateTable"], resources=[table.table_arn]
            )
        )
        on_event_handler = Function(
            self,
            "OnEventHandler",
            runtime=Runtime.PYTHON_3_12,
            handler="handler.on_event",
            code=Code.from_asset(str(_LAMBDA_ASSET_DIR)),
            layers=[boto3_layer],
            environment=environment,
            timeout=Duration.seconds(30),
            log_group=on_event_log_group,
            role=on_event_role,
        )

        is_complete_log_group = LogGroup(
            self,
            "IsCompleteLogs",
            retention=RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        is_complete_role = self._bare_lambda_role(
            "IsCompleteHandlerRole", is_complete_log_group
        )
        is_complete_role.add_to_principal_policy(
            PolicyStatement(
                actions=["dynamodb:DescribeTable"], resources=[table.table_arn]
            )
        )
        # dynamodb:SearchVectors is a separate IAM action from table-level reads, scoped
        # to the INDEX arn specifically (not the table arn) - easy to miss, and FGAC
        # condition keys don't apply to it regardless of scope (docs/api-notes.md
        # section (b)).
        is_complete_role.add_to_principal_policy(
            PolicyStatement(actions=["dynamodb:SearchVectors"], resources=[index_arn])
        )
        is_complete_handler = Function(
            self,
            "IsCompleteHandler",
            runtime=Runtime.PYTHON_3_12,
            handler="handler.is_complete",
            code=Code.from_asset(str(_LAMBDA_ASSET_DIR)),
            layers=[boto3_layer],
            environment=environment,
            timeout=Duration.seconds(30),
            log_group=is_complete_log_group,
            role=is_complete_role,
        )

        # The Provider construct creates its own internal proxy Lambdas
        # (framework-onEvent, framework-isComplete, framework-onTimeout) to drive its
        # state machine - separate from OnEventHandler/IsCompleteHandler above, which
        # are our own functions. Left at Provider's default, those proxies let Lambda
        # auto-create their log groups implicitly on first invocation, with no
        # CloudFormation record and no retention set - orphans that `cdk destroy`
        # cannot remove (verified live: docs/api-notes.md, "Teardown finding: CDK
        # Provider framework orphans two log groups"). Provider's `log_group` prop
        # wires all three internal proxies to one explicit, stack-managed LogGroup
        # instead, verified by inspecting the synthesized template: it appears as a
        # single AWS::Logs::LogGroup with DeletionPolicy: Delete, referenced by each
        # proxy Lambda's own LoggingConfig.LogGroup.
        provider_framework_log_group = LogGroup(
            self,
            "ProviderFrameworkLogs",
            retention=RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        provider = Provider(
            self,
            "Provider",
            on_event_handler=on_event_handler,
            is_complete_handler=is_complete_handler,
            query_interval=Duration.seconds(15),
            # Capped well below the default 1 hour: a stuck custom resource that
            # CloudFormation can't roll back for an hour is a worse failure mode for
            # this repo than a clean rejection. The Lambda's own is_complete handler
            # fails loudly with a specific diagnostic message before this (at
            # _MAX_WAIT_SECONDS in handler.py, ~11 minutes) so that message - not a
            # generic framework timeout - is what surfaces if something hangs.
            total_timeout=Duration.minutes(15),
            log_group=provider_framework_log_group,
        )

        self.resource = CustomResource(
            self,
            "Resource",
            service_token=provider.service_token,
            resource_type="Custom::DynamoDBVectorIndex",
            # Every value that identifies this index, as an explicit CloudFormation
            # property on the custom resource itself (not just a Lambda environment
            # variable) - so a change to any of them actually produces an Update event
            # CloudFormation notices and delivers to on_event, where it's rejected
            # loudly (see handler.py's _on_update) rather than silently leaving the
            # deployed index out of sync with a config change that never got applied.
            properties={
                "IndexName": VECTOR_INDEX_NAME,
                "VectorAttributeName": VECTOR_ATTRIBUTE_NAME,
                "CategoryAttributeName": CATEGORY_ATTRIBUTE_NAME,
                "Dimensions": EMBEDDING_DIMENSIONS,
                "DistanceFunction": DISTANCE_FUNCTION,
            },
        )

        self.index_name = VECTOR_INDEX_NAME
        self.index_arn = index_arn

    def _bare_lambda_role(self, construct_id: str, log_group: LogGroup) -> Role:
        # Function's default auto-created role attaches the AWS-managed
        # AWSLambdaBasicExecutionRole policy even when an explicit log_group is given -
        # that policy grants logs:CreateLogGroup/CreateLogStream/PutLogEvents on
        # Resource: "arn:aws:logs:*:*:*" (an ARN-pattern wildcard, not a literal "*",
        # so it wouldn't be caught by tests/test_template.py's wildcard check - but it's
        # still broader than this repo's "IAM scoped to exact resource ARNs" rule
        # intends for anything we author). Building the role ourselves - no managed
        # policies, only a log-write statement scoped to this function's own specific
        # log group - keeps every permission on these two handlers exactly as narrow as
        # the rest of this construct's grants.
        role = Role(
            self, construct_id, assumed_by=ServicePrincipal("lambda.amazonaws.com")
        )
        role.add_to_principal_policy(
            PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[log_group.log_group_arn, f"{log_group.log_group_arn}:*"],
            )
        )
        return role
