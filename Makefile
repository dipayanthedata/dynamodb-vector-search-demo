.PHONY: install lint test synth diff clean build-layer

# boto3/botocore pinned to a version new enough for search_vectors/VectorIndexUpdates
# (docs/api-notes.md section (d)) - the managed Lambda runtime's own bundled version
# can't be trusted for a feature this new. Installed via plain pip -t, not
# PythonFunction/Docker bundling: both boto3 and botocore are pure Python (no compiled
# extensions), so a host-only pip install produces an identical, portable artifact
# regardless of the build machine's OS/architecture - no container runtime needed,
# keeping a fresh clone deployable within the 30-minute budget.
BOTO3_VERSION := 1.43.87
BOTOCORE_VERSION := 1.43.87

install: ## Install CDK + dev dependencies
	python3 -m pip install -r infra/requirements.txt -r requirements-dev.txt

build-layer: ## Bundle a pinned boto3/botocore as a Lambda layer asset (no Docker)
	rm -rf build/layer
	mkdir -p build/layer/python
	python3 -m pip install \
		boto3==$(BOTO3_VERSION) botocore==$(BOTOCORE_VERSION) \
		-t build/layer/python --no-cache-dir -q

lint: ## Lint and format-check everything
	ruff check .
	ruff format --check .

test: build-layer ## Run the test suite (CDK template assertions, unit tests)
	pytest -q

synth: build-layer ## Synthesize CloudFormation without deploying
	cd infra && cdk synth

diff: build-layer ## Show what a deploy would change (safe, no changes made)
	cd infra && cdk diff

clean: ## Remove build artifacts
	rm -rf infra/cdk.out build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
	find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
