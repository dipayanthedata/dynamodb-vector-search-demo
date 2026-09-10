"""Stages a Lambda handler directory plus any shared local packages it imports into
a directory under build/, so Code.from_asset can zip one flat directory containing
everything the handler needs at its top level - handler.py's own files, plus e.g.
`shared/` as a subpackage sitting right next to it.

This repo's Lambda handler directories (lambda/<name>/) are zipped directly, not
the repo root, because the repo's own top-level `lambda/` directory can't appear in
a dotted handler string - `lambda` is a Python reserved word, so
`lambda.ingest.handler.handler` isn't importable. That means a handler that imports
from `shared/` (which lives at the repo root, alongside `lambda/`, for the CDK app
to import too - see shared/vector_config.py) needs `shared/` physically copied in
beside it before zipping; that's what this module does. It's a plain file copy, not
a pip install, so - unlike build/layer - it runs on every `cdk synth` rather than
needing its own cached `make` target.
"""

import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BUILD_ROOT = _REPO_ROOT / "build" / "lambda_assets"


def stage_lambda_asset(lambda_dir: Path, shared_packages: list[str]) -> str:
    """Copies `lambda_dir`'s own files, plus each named top-level package from the
    repo root (e.g. ["shared"]), into build/lambda_assets/<lambda_dir.name>/.
    Returns that staged directory's path, ready for `Code.from_asset`.
    """
    staged_dir = _BUILD_ROOT / lambda_dir.name
    if staged_dir.exists():
        shutil.rmtree(staged_dir)
    shutil.copytree(lambda_dir, staged_dir)
    for package_name in shared_packages:
        shutil.copytree(_REPO_ROOT / package_name, staged_dir / package_name)
    return str(staged_dir)
