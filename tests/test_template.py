"""CDK template assertions - the guardrails from CLAUDE.md, enforced from the first
real resource onward rather than bolted on at the end. Every later build step's
resources get checked against the same assertions here as the stack grows.
"""

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from stacks import VectorSearchStack

from shared.vector_config import EMBEDDING_DIMENSIONS


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    stack = VectorSearchStack(
        app,
        "TestStack",
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_table_is_pay_per_request(template: Template) -> None:
    # Vector indexes require on-demand capacity - see docs/api-notes.md fact #4.
    template.has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {"BillingMode": "PAY_PER_REQUEST"},
    )


def test_table_removal_policy_is_delete(template: Template) -> None:
    # Everything this repo creates must be removed by `cdk destroy` - CLAUDE.md.
    template.has_resource(
        "AWS::DynamoDB::GlobalTable",
        {"DeletionPolicy": "Delete"},
    )


def test_table_attribute_definitions_do_not_yet_include_category(
    template: Template,
) -> None:
    # `category` becomes the vector index's INLINE_FILTER attribute, but it is
    # deliberately NOT in this step's AttributeDefinitions - CreateTable rejects any
    # attribute definition not referenced by a key schema or index in the same call,
    # and TableV2 has no prop to add an unreferenced one. It's added in the next
    # step's UpdateTable call instead (see docs/api-notes.md section (a), and the
    # comment in vector_search_stack.py). This test asserts the correct base-table
    # state now, so a future change that tries to add `category` here directly (which
    # would fail at deploy time) gets caught immediately instead of at `cdk deploy`.
    template.has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "AttributeDefinitions": [
                {"AttributeName": "docId", "AttributeType": "S"},
            ],
        },
    )


def test_no_vpc_anywhere(template: Template) -> None:
    # No VPC, no NAT - CLAUDE.md / the article's constraint list.
    template.resource_count_is("AWS::EC2::VPC", 0)


def test_no_nat_gateway_anywhere(template: Template) -> None:
    template.resource_count_is("AWS::EC2::NatGateway", 0)


def test_no_implicit_lambda_log_groups(template: Template) -> None:
    # Every Lambda function (including the CDK Provider framework's own internal
    # onEvent/isComplete/onTimeout proxies) must be wired to an explicit,
    # stack-managed LogGroup via LoggingConfig - not left to Lambda's default of
    # auto-creating one implicitly on first invocation. An implicit log group has no
    # CloudFormation record, so `cdk destroy` can't remove it - see docs/api-notes.md,
    # "Teardown finding: CDK Provider framework orphans two log groups", and CLAUDE.md's
    # "Full teardown" rule. Regression guardrail for the fix in
    # infra/custom_constructs/vector_index.py (Provider's `log_group` prop).
    rendered = template.to_json()
    log_group_ids = {
        logical_id
        for logical_id, resource in rendered["Resources"].items()
        if resource["Type"] == "AWS::Logs::LogGroup"
    }
    for logical_id, resource in rendered["Resources"].items():
        if resource["Type"] != "AWS::Lambda::Function":
            continue
        logging_config = resource["Properties"].get("LoggingConfig")
        assert logging_config and "LogGroup" in logging_config, (
            f"{logical_id} has no explicit LogGroup wired via LoggingConfig - "
            "it will orphan an implicitly-created log group on cdk destroy"
        )
        ref = logging_config["LogGroup"].get("Ref")
        assert ref in log_group_ids, (
            f"{logical_id}'s LoggingConfig.LogGroup does not reference a "
            "stack-managed AWS::Logs::LogGroup resource"
        )


def test_all_log_groups_removal_policy_is_delete(template: Template) -> None:
    # Every log group this stack creates (including the Provider framework's own,
    # see test_no_implicit_lambda_log_groups above) must be removed by `cdk destroy` -
    # CLAUDE.md's "Full teardown" rule.
    rendered = template.to_json()
    for logical_id, resource in rendered["Resources"].items():
        if resource["Type"] == "AWS::Logs::LogGroup":
            assert resource.get("DeletionPolicy") == "Delete", (
                f"{logical_id} is missing RemovalPolicy.DESTROY"
            )


def test_no_iam_wildcard_resource(template: Template) -> None:
    # IAM scoped to exact resource ARNs, no wildcards - CLAUDE.md. Checked broadly
    # across every resource type CDK might embed a policy document in (standalone
    # AWS::IAM::Policy, inline Role policies, AWS::IAM::ManagedPolicy), not just one
    # specific shape, since CDK's choice of where to place a policy document varies.
    # Trivially passes today (no IAM resources exist yet at this build step) - this
    # is a forward guardrail for every later step that adds one.
    rendered = template.to_json()
    violations = []

    def walk(node, path):
        if isinstance(node, dict):
            if "Resource" in node:
                resource = node["Resource"]
                values = resource if isinstance(resource, list) else [resource]
                if any(v == "*" for v in values):
                    violations.append(path)
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    for logical_id, resource in rendered.get("Resources", {}).items():
        if resource.get("Type", "").startswith("AWS::IAM::"):
            walk(resource, logical_id)

    assert not violations, f"Found wildcard IAM Resource in: {violations}"


def test_custom_resources_wired_to_provider(template: Template) -> None:
    # Every custom resource must have a ServiceToken wired to a CDK Provider so
    # the framework routes CloudFormation Delete events to an onDelete handler.
    # The actual delete logic (UpdateTable with VectorIndexUpdates Delete) is
    # tested in unit tests (tests/test_vector_index_manager_handler.py
    # test_on_delete_calls_update_table_with_delete) - this is just a template
    # structure check that the wiring is present.
    rendered = template.to_json()
    violations = []

    for logical_id, resource in rendered.get("Resources", {}).items():
        if resource.get("Type") == "AWS::CloudFormation::CustomResource":
            service_token = resource.get("Properties", {}).get("ServiceToken")
            if not service_token:
                violations.append(
                    f"{logical_id}: no ServiceToken (Provider not wired for delete routing)"
                )

    assert not violations, f"Custom resources missing ServiceToken: {violations}"


def test_embedding_dimension_consistent_with_config(template: Template) -> None:
    # The embedding dimension constant (shared/vector_config.py) is the single
    # source of truth for EMBEDDING_DIMENSIONS. All Lambda functions (ingest, search)
    # must read it from environment variables set by the CDK constructs that import
    # the shared constant. This test verifies the constant value makes it into the
    # template, so a divergence between shared/vector_config.py and the CDK code
    # (or a typo in environment variable name) gets caught immediately, not at deploy
    # time. Related to CLAUDE.md rule: "Never invent an AWS API parameter."
    rendered = template.to_json()

    ingest_found = False
    for logical_id, resource in rendered["Resources"].items():
        if resource["Type"] != "AWS::Lambda::Function":
            continue
        env_vars = resource["Properties"].get("Environment", {}).get("Variables", {})
        if "EMBEDDING_DIMENSIONS" in env_vars:
            value = int(env_vars["EMBEDDING_DIMENSIONS"])
            assert value == EMBEDDING_DIMENSIONS, (
                f"{logical_id} has EMBEDDING_DIMENSIONS={value}, expected {EMBEDDING_DIMENSIONS}"
            )
            ingest_found = True

    assert ingest_found, (
        "No Lambda function found with EMBEDDING_DIMENSIONS env var - ingest handler may not be deployed"
    )


def test_ingest_lambda_function_deployed(template: Template) -> None:
    # IngestFunction must be present in the stack - it embeds documents and writes
    # them to the table. If the construct is defined but never instantiated, this
    # catches it via template assertions (phantom coverage guard per CLAUDE.md).
    rendered = template.to_json()
    found = False
    for resource in rendered["Resources"].values():
        if resource["Type"] != "AWS::Lambda::Function":
            continue
        env_vars = (
            resource.get("Properties", {}).get("Environment", {}).get("Variables", {})
        )
        if "TABLE_NAME" in env_vars:
            found = True
            break
    assert found, (
        "IngestFunction not deployed - no Lambda function found with TABLE_NAME env var"
    )


def test_search_lambda_function_deployed(template: Template) -> None:
    # SearchFunction must be present in the stack - it embeds queries and searches
    # the vector index. If the construct is defined but never instantiated, this
    # catches it via template assertions.
    rendered = template.to_json()
    found = False
    for resource in rendered["Resources"].values():
        if resource["Type"] != "AWS::Lambda::Function":
            continue
        env_vars = (
            resource.get("Properties", {}).get("Environment", {}).get("Variables", {})
        )
        if "VECTOR_INDEX_NAME" in env_vars:
            found = True
            break
    assert found, (
        "SearchFunction not deployed - no Lambda function found with VECTOR_INDEX_NAME env var"
    )


def test_boto3_layer_deployed(template: Template) -> None:
    # Boto3 layer must be present in the stack to provide a newer version of boto3
    # (with search_vectors support) than the Lambda managed runtime's bundled version.
    # If the layer is deleted or never instantiated, this catches it.
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)


def test_search_vectors_policy_scoped_to_index_arn(template: Template) -> None:
    # SearchVectors IAM action requires the vector INDEX ARN
    # (arn:aws:dynamodb:region:account:table/NAME/index/INDEX), not table ARN.
    # CloudFormation renders this as Fn::Join of table ARN + "/index/INDEX".
    # This test verifies the construct includes /index/ in the resource.
    # If resources=[table.table_arn] instead, this assertion fails.
    import json

    rendered = template.to_json()
    found_search_vectors_with_index = False

    for rid, resource in rendered["Resources"].items():
        if resource["Type"] != "AWS::IAM::Policy":
            continue
        if "SearchFunction" not in rid:
            continue
        doc = resource["Properties"].get("PolicyDocument", {})
        for stmt in doc.get("Statement", []):
            actions = stmt.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            if "dynamodb:SearchVectors" not in actions:
                continue
            # Found SearchVectors statement. Serialize Resource to JSON to check
            # for /index/ in the rendered form (CDK uses Fn::Join for ARNs).
            res = stmt.get("Resource")
            res_str = json.dumps(res)
            # Index ARN format: arn:aws:dynamodb:region:account:table/X/index/Y
            # Fn::Join concatenates table ARN + "/index/INDEX_NAME"
            if "/index/" in res_str:
                found_search_vectors_with_index = True

    assert found_search_vectors_with_index, (
        "SearchVectors IAM policy not found on SearchFunction with index ARN. "
        "Must use vector_index.index_arn, not table.table_arn. "
        "The rendered resource should contain /index/ when serialized."
    )


def test_lambda_function_count(template: Template) -> None:
    # The stack deploys exactly 5 Lambda functions:
    # - IngestFunction/Function (user-deployed, embeds & writes)
    # - SearchFunction/Function (user-deployed, embeds & searches)
    # - VectorIndex/OnEventHandler (CDK Provider, CreateTable UpdateTable)
    # - VectorIndex/IsCompleteHandler (CDK Provider, polls UpdateTable status)
    # - VectorIndex/framework-onEvent (CDK Provider framework wrapper)
    # Plus 2 more internal framework functions (onTimeout, isComplete framework wrappers).
    # Total: 7 Lambda functions. This test catches missing user-deployed functions
    # (ingest or search) without being overly brittle to internal Provider changes.
    template.resource_count_is("AWS::Lambda::Function", 7)
