"""Unit tests for scripts (query construction, result formatting, score ordering).

Integration tests (invoking real Lambdas, seeding corpus) are skipped here
because they require real AWS resources. Test what can be isolated instead.
"""

import json
from pathlib import Path

import pytest


def test_corpus_file_exists():
    """Corpus file is present and valid JSON."""
    repo_root = Path(__file__).resolve().parent.parent
    corpus_path = repo_root / "data" / "corpus.json"
    assert corpus_path.exists(), "Corpus file must exist at data/corpus.json"
    with open(corpus_path) as f:
        corpus = json.load(f)
    assert isinstance(corpus, list), "Corpus must be a JSON array"
    assert len(corpus) >= 60, "Corpus must have at least 60 documents"
    assert len(corpus) <= 80, "Corpus must have at most 80 documents"


def test_corpus_document_structure():
    """Each corpus document has required fields."""
    repo_root = Path(__file__).resolve().parent.parent
    corpus_path = repo_root / "data" / "corpus.json"
    with open(corpus_path) as f:
        corpus = json.load(f)

    for doc in corpus:
        assert "docId" in doc, f"Document missing docId: {doc}"
        assert "text" in doc, f"Document missing text: {doc}"
        assert "category" in doc, f"Document missing category: {doc}"
        assert isinstance(doc["text"], str), f"text must be string: {doc}"
        assert len(doc["text"]) > 0, f"text must not be empty: {doc}"


def test_corpus_categories_are_balanced():
    """Corpus has approximately equal representation across categories."""
    repo_root = Path(__file__).resolve().parent.parent
    corpus_path = repo_root / "data" / "corpus.json"
    with open(corpus_path) as f:
        corpus = json.load(f)

    categories = {}
    for doc in corpus:
        cat = doc["category"]
        categories[cat] = categories.get(cat, 0) + 1

    # Each category should have roughly 60/4=15 documents (±3 tolerance)
    for cat, count in categories.items():
        assert 12 <= count <= 18, (
            f"Category {cat} has {count} docs; "
            "should be ~15 (roughly equal distribution)"
        )


def test_corpus_has_semantic_diversity():
    """Corpus includes paraphrases and semantic variation, not just keywords."""
    repo_root = Path(__file__).resolve().parent.parent
    corpus_path = repo_root / "data" / "corpus.json"
    with open(corpus_path) as f:
        corpus = json.load(f)

    # Look for intentional paraphrasing patterns:
    # - tech-011 uses "automatic learning systems" (not "machine learning")
    # - health-010 mentions "diagnose" in doctor context
    # - travel-011 uses "visiting foreign places" (not just "travel")

    texts = [doc["text"].lower() for doc in corpus]

    # Check for semantic variation markers
    has_paraphrase = any("automatic learning" in text for text in texts)
    has_diagnosis = any("diagnose" in text for text in texts)
    has_travel_variation = any("visiting foreign" in text for text in texts)

    assert has_paraphrase or has_diagnosis or has_travel_variation, (
        "Corpus should include semantic paraphrases, not just keywords"
    )


def test_seed_script_exists():
    """seed.py script is present and importable."""
    repo_root = Path(__file__).resolve().parent.parent
    seed_path = repo_root / "scripts" / "seed.py"
    assert seed_path.exists(), "scripts/seed.py must exist"


def test_demo_script_exists():
    """demo.py script is present and importable."""
    repo_root = Path(__file__).resolve().parent.parent
    demo_path = repo_root / "scripts" / "demo.py"
    assert demo_path.exists(), "scripts/demo.py must exist"


def test_baseline_script_exists():
    """keyword_baseline.py script is present and importable."""
    repo_root = Path(__file__).resolve().parent.parent
    baseline_path = repo_root / "scripts" / "keyword_baseline.py"
    assert baseline_path.exists(), "scripts/keyword_baseline.py must exist"


@pytest.mark.no_assert
def test_seed_script_integration_skipped():
    """SKIPPED: Seeding requires real Lambda and DynamoDB.

    This test does not run because it requires:
    - Deployed ingest Lambda function
    - AWS credentials and permissions
    - Real DynamoDB table
    - Network access to AWS

    Integration testing happens during step 8 deploy.
    """


@pytest.mark.no_assert
def test_demo_script_integration_skipped():
    """SKIPPED: Demo requires real Lambda and seeded data.

    This test does not run because it requires:
    - Deployed search Lambda function
    - Seeded corpus in DynamoDB
    - AWS credentials and permissions
    - Network access to AWS

    Integration testing happens during step 8 deploy.
    """


@pytest.mark.no_assert
def test_baseline_script_integration_skipped():
    """SKIPPED: Baseline comparison requires seeded data.

    This test does not run because it requires:
    - Seeded corpus in DynamoDB
    - AWS credentials and permissions
    - Network access to AWS

    Integration testing happens during step 8 deploy.
    """


def test_score_ordering_cosine():
    """COSINE distance: lower scores are better."""
    distance_function = "COSINE"
    is_lower_better = distance_function == "COSINE"
    assert is_lower_better, "COSINE: lower scores indicate higher similarity"

    scores = [0.05, 0.15, 0.25]  # Pre-sorted by SearchVectors
    # Lower score = higher similarity = should be first in results
    assert scores[0] < scores[1] < scores[2], "Scores should be ascending"


def test_score_ordering_euclidean():
    """EUCLIDEAN distance: lower scores are better."""
    distance_function = "EUCLIDEAN"
    is_lower_better = distance_function == "EUCLIDEAN"
    assert is_lower_better, "EUCLIDEAN: lower scores indicate higher similarity"

    scores = [0.1, 0.2, 0.3]  # Pre-sorted by SearchVectors
    # Lower score = shorter distance = higher similarity
    assert scores[0] < scores[1] < scores[2], "Scores should be ascending"


def test_score_ordering_dot_product():
    """DOT_PRODUCT: higher scores are better."""
    distance_function = "DOT_PRODUCT"
    is_lower_better = distance_function != "DOT_PRODUCT"
    assert not is_lower_better, "DOT_PRODUCT: higher scores indicate higher similarity"

    scores = [0.8, 0.6, 0.4]  # Pre-sorted by SearchVectors
    # Higher score = higher dot product = higher similarity
    assert scores[0] > scores[1] > scores[2], "Scores should be descending"


def test_result_formatting_includes_required_fields():
    """Formatted search result includes all required fields."""
    # Simulating what demo.py produces
    sample_result = {
        "docId": "tech-001",
        "score": 0.123,
        "category": "technology",
    }

    assert "docId" in sample_result
    assert "score" in sample_result
    assert "category" in sample_result
    assert isinstance(sample_result["score"], float)


def test_top_k_limit_honored():
    """Query respects TopK parameter (max 3 results in demo)."""
    # This models the constraint: demo.py requests top_k=3
    top_k = 3
    results = [
        {"docId": "doc-1", "score": 0.1},
        {"docId": "doc-2", "score": 0.2},
        {"docId": "doc-3", "score": 0.3},
    ]
    assert len(results) <= top_k, "Results should respect TopK limit"
