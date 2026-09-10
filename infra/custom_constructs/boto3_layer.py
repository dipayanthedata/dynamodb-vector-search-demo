"""Builds the shared pinned boto3/botocore Lambda layer asset (build/layer, built
by `make build-layer` - see docs/api-notes.md section (d)). Built once per stack
and shared by every Lambda that needs a boto3 newer than the managed runtime's own
bundled version, so the pin lives in one CloudFormation resource, not one per
function.
"""

from pathlib import Path

from aws_cdk import RemovalPolicy
from aws_cdk.aws_lambda import Code, LayerVersion, Runtime
from constructs import Construct

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LAYER_ASSET_DIR = _REPO_ROOT / "build" / "layer"


def build_boto3_layer(scope: Construct, construct_id: str) -> LayerVersion:
    if not _LAYER_ASSET_DIR.exists():
        raise RuntimeError(
            f"{_LAYER_ASSET_DIR} does not exist - run `make build-layer` first "
            "(or `make synth` / `make test`, which both depend on it). This "
            "bundles a boto3/botocore new enough for search_vectors and "
            "VectorIndexUpdates without needing Docker - see "
            "docs/api-notes.md section (d)."
        )
    return LayerVersion(
        scope,
        construct_id,
        code=Code.from_asset(str(_LAYER_ASSET_DIR)),
        compatible_runtimes=[Runtime.PYTHON_3_12],
        removal_policy=RemovalPolicy.DESTROY,
    )
