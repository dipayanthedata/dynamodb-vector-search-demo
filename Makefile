.PHONY: install lint test synth diff clean

install: ## Install CDK + dev dependencies
	python3 -m pip install -r infra/requirements.txt -r requirements-dev.txt

lint: ## Lint and format-check everything
	ruff check .
	ruff format --check .

test: ## Run the test suite (CDK template assertions, unit tests)
	pytest -q

synth: ## Synthesize CloudFormation without deploying
	cd infra && cdk synth

diff: ## Show what a deploy would change (safe, no changes made)
	cd infra && cdk diff

clean: ## Remove build artifacts
	rm -rf infra/cdk.out
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
	find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
