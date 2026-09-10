"""Serializes a list of floats to/from the two different wire shapes DynamoDB's
vector search API uses for the same underlying data - see docs/api-notes.md's
"AttributeValue - the L/N vs. plain-array asymmetry" section:

- An item's stored vector attribute (PutItem/UpdateItem/BatchWriteItem): a List
  attribute value, each element a Number - i.e. {"L": [{"N": "..."}, ...]}.
- The SearchVectors request's `SearchVector` parameter: a bare array of Number
  AttributeValue objects, with no outer "L" wrapper - i.e. [{"N": "..."}, ...].

Both directions live here, imported by both the ingest Lambda (writes, needs the
`L` wrapper) and the search Lambda (queries, needs the bare array), so the two
representations cannot silently drift apart - see docs/api-notes.md's
"Implementation consequence" note under section (b).
"""

import math
from decimal import Decimal


def _format_number(value: float) -> str:
    # DynamoDB's N type is a string on the wire. repr() gives the shortest string
    # that round-trips to the same float - exactly what's wanted here - except it
    # can use scientific notation ("1e-08") for very small magnitudes, which is
    # reformatted to plain fixed-point via Decimal rather than risk it being
    # misinterpreted.
    # Reject NaN and infinity explicitly - they produce "nan"/"inf" strings which
    # are not valid DynamoDB N values and would cause silent bugs or service rejection.
    fval = float(value)
    if math.isnan(fval):
        raise ValueError("NaN is not a valid vector component")
    if math.isinf(fval):
        raise ValueError(f"Infinity is not a valid vector component: {fval}")
    text = repr(fval)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


def to_stored_vector(values: list[float]) -> dict:
    """The item attribute value for a vector written to the base table: a
    DynamoDB List of Numbers, e.g. {"L": [{"N": "0.1234"}, {"N": "-0.5678"}]}.
    """
    return {"L": [{"N": _format_number(v)} for v in values]}


def to_search_vector(values: list[float]) -> list[dict]:
    """The `SearchVector` request parameter for SearchVectors: a bare array of
    Number AttributeValue objects, e.g. [{"N": "0.1234"}, {"N": "-0.5678"}] - no
    outer "L" wrapper, unlike the stored representation above (docs/api-notes.md
    section (b)).
    """
    return [{"N": _format_number(v)} for v in values]
