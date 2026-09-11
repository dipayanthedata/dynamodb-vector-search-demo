"""Unit tests for shared/vector_serialization.py - the module both the ingest and
search Lambdas import for the stored-vs-search vector wire shape asymmetry
(docs/api-notes.md section (b)). This is the highest-risk module in the repo:
a silent serialization error produces plausible garbage results, not an exception.

Tests include:
1. Literal expected-output assertions against docs/api-notes.md's cited shapes
2. Cross-consistency check (to_search_vector output == inner list of to_stored_vector)
3. Edge cases: very small magnitudes, high precision, zero variants, invalid inputs
"""

import pytest

from shared.vector_serialization import to_search_vector, to_stored_vector

# Correctness tests: literal expected output from docs/api-notes.md API shapes


def test_to_stored_vector_literal_shape():
    # From docs/api-notes.md (b): stored item vector is {"L": [{"N": "..."}, ...]}
    result = to_stored_vector([0.125, -0.5])
    assert result == {"L": [{"N": "0.125"}, {"N": "-0.5"}]}


def test_to_search_vector_literal_shape():
    # From docs/api-notes.md (b): SearchVector param is bare [{"N": "..."}, ...]
    # (no outer "L" wrapper unlike stored vector)
    result = to_search_vector([0.125, -0.5])
    assert result == [{"N": "0.125"}, {"N": "-0.5"}]


def test_common_cases():
    # Multiple values, positive/negative, including exact representations
    assert to_stored_vector([0.5, -0.25, 0.0]) == {
        "L": [{"N": "0.5"}, {"N": "-0.25"}, {"N": "0.0"}]
    }
    assert to_search_vector([0.5, -0.25, 0.0]) == [
        {"N": "0.5"},
        {"N": "-0.25"},
        {"N": "0.0"},
    ]


# Consistency check: internal invariant (separate from correctness)


def test_to_search_vector_matches_inner_list_of_to_stored_vector():
    # Both directions must stay synchronized - if one changes, the other must too.
    # This is not a correctness check; it's a guard against silent divergence.
    values = [0.1, -0.2, 0.3, 1.0, -1.0]
    assert to_search_vector(values) == to_stored_vector(values)["L"]


# Edge cases: precision, magnitude, special values


def test_very_small_magnitudes_avoid_scientific_notation():
    # repr(1e-05) == "1e-05", repr(1.2e-07) == "1.2e-07".
    # DynamoDB's N type is a string on the wire (docs/api-notes.md section (b)).
    # docs/api-notes.md section (d) states the formatter converts scientific notation
    # to fixed-point via Decimal to avoid misinterpretation.
    for small_value in [1e-05, 1.2e-07]:
        formatted = to_stored_vector([small_value])["L"][0]["N"]
        assert "e" not in formatted.lower(), (
            f"Scientific notation not allowed in DynamoDB N type: {formatted}"
        )
        assert float(formatted) == small_value, (
            f"Formatter lost precision: {formatted} != {small_value}"
        )


def test_high_precision_values():
    # Bedrock Titan returns float32 (32-bit IEEE-754 per docs/api-notes.md).
    # Input may have more precision than float32 holds, but Python rounds on
    # conversion to float, so the value stored is what float32 would hold anyway.
    # repr() of that float gives the shortest decimal that round-trips, which is
    # what we want - no extra rounding/quantization needed.
    high_precision = 0.12345678901234567
    # Python converts to float32-equivalent precision on input
    result = to_stored_vector([high_precision])
    stored_value = float(result["L"][0]["N"])
    # Verify round-trip: stored string parses back to the same float value
    assert stored_value == high_precision


def test_zero_and_negative_zero():
    # IEEE-754: -0.0 == 0.0 in value, but repr() preserves the sign.
    # Both are valid and representable; preserve the sign as passed.
    zero_result = to_stored_vector([0.0])
    neg_zero_result = to_stored_vector([-0.0])
    assert zero_result == {"L": [{"N": "0.0"}]}
    assert neg_zero_result == {"L": [{"N": "-0.0"}]}
    # They compare equal in value (IEEE-754 standard)
    assert float(zero_result["L"][0]["N"]) == float(neg_zero_result["L"][0]["N"])


def test_all_zeros_vector():
    # Degenerate case: vector of all zeros
    result = to_stored_vector([0.0, 0.0, 0.0])
    assert result == {"L": [{"N": "0.0"}, {"N": "0.0"}, {"N": "0.0"}]}


def test_nan_rejected():
    # NaN must be rejected with a clear error, not silently produce garbage.
    with pytest.raises((ValueError, TypeError)):
        to_stored_vector([float("nan")])


def test_infinity_rejected():
    # Infinity must be rejected with a clear error.
    with pytest.raises((ValueError, TypeError)):
        to_stored_vector([float("inf")])
    with pytest.raises((ValueError, TypeError)):
        to_stored_vector([float("-inf")])
