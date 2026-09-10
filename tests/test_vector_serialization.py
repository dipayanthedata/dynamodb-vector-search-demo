"""Unit tests for shared/vector_serialization.py - the module both the ingest and
search Lambdas import for the stored-vs-search vector wire shape asymmetry
(docs/api-notes.md section (b)). The round-trip test is the one the module's own
docstring commits to: to_search_vector's output must equal the inner list of
to_stored_vector's "L", so the two functions cannot silently drift apart.
"""

from shared.vector_serialization import to_search_vector, to_stored_vector


def test_to_stored_vector_wraps_in_l_of_n():
    assert to_stored_vector([0.5, -0.25, 0.0]) == {
        "L": [{"N": "0.5"}, {"N": "-0.25"}, {"N": "0.0"}]
    }


def test_to_search_vector_is_bare_array_of_n():
    assert to_search_vector([0.5, -0.25, 0.0]) == [
        {"N": "0.5"},
        {"N": "-0.25"},
        {"N": "0.0"},
    ]


def test_to_search_vector_matches_inner_list_of_to_stored_vector():
    values = [0.1, -0.2, 0.3, 1.0, -1.0]
    assert to_search_vector(values) == to_stored_vector(values)["L"]


def test_small_magnitudes_avoid_scientific_notation():
    # repr(1e-08) == "1e-08" - DynamoDB's N type must not receive that form.
    formatted = to_stored_vector([1e-08])["L"][0]["N"]
    assert "e" not in formatted.lower()
    assert float(formatted) == 1e-08
