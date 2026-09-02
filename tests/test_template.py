"""CDK template assertions - the guardrails from CLAUDE.md, enforced from the first
real resource onward rather than bolted on at the end. Every later build step's
resources get checked against the same assertions here as the stack grows.
"""

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template
from stacks import VectorSearchStack


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
