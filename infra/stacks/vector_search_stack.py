"""DynamoDB native vector search demo: base table, vector index, ingest + search Lambdas.

Built incrementally - resources are added one build-order step at a time (see
CLAUDE.md / commit history), each step verified with `cdk synth` before the next.
This step: empty stack skeleton only, to prove the app/env wiring synths cleanly
before any real resource is added.
"""

from aws_cdk import Stack
from constructs import Construct


class VectorSearchStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
