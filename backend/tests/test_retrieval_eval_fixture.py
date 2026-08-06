"""Validate the retrieval evaluation fixture.

These run offline: no database, no API key, no network. They exist because the
fixture's expectations are only meaningful if each expected substring identifies
exactly ONE chunk, and that property is silently destroyed by editing a case, by
changing CHUNK_MAX_CHARS, or by re-fetching a transcript whose captions shifted.

A substring that lands in two chunks does not fail loudly - it makes its case
pass for the wrong reason, which is worse than a failure because the resulting
hit rate still looks like evidence. Seven candidate substrings were rejected
while the fixture was written; "try and accept" and "hey there" both read as
obviously distinctive and both appear in two chunks.
"""

import json
from pathlib import Path

import pytest

from app.schemas.transcript import TranscriptResponse
from app.services.chunking_service import build_semantic_chunks

FIXTURES = Path(__file__).parent / "fixtures"
CASES_PATH = FIXTURES / "retrieval_eval_cases.json"

# The sizes the fixture claims to be valid at. 600 is the current default; the
# others bracket it so a future tuning run does not silently invalidate the set.
CHUNK_SIZES = [450, 600, 900, 1200]
OVERLAP_SEGMENTS = 1


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def transcript(fixture_data) -> TranscriptResponse:  # noqa: ANN001
    path = FIXTURES / fixture_data["transcript_fixture"]
    return TranscriptResponse.model_validate_json(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chunks_by_size(transcript) -> dict:  # noqa: ANN001
    return {
        size: build_semantic_chunks(
            transcript=transcript, max_chunk_chars=size, overlap_segments=OVERLAP_SEGMENTS
        )
        for size in CHUNK_SIZES
    }


def content_cases(fixture_data) -> list[dict]:  # noqa: ANN001
    return [c for c in fixture_data["cases"] if c["kind"] != "off_topic"]


def test_every_case_has_a_unique_id(fixture_data) -> None:  # noqa: ANN001
    ids = [c["id"] for c in fixture_data["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids make results impossible to attribute"


@pytest.mark.parametrize("size", CHUNK_SIZES)
def test_expected_substrings_identify_exactly_one_chunk(fixture_data, chunks_by_size, size) -> None:  # noqa: ANN001
    chunks = chunks_by_size[size]
    ambiguous = {}
    for case in content_cases(fixture_data):
        needle = case["expect_chunk_containing"].lower()
        count = sum(1 for chunk in chunks if needle in chunk.text.lower())
        if count != 1:
            ambiguous[case["id"]] = (case["expect_chunk_containing"], count)

    assert not ambiguous, (
        f"at CHUNK_MAX_CHARS={size} these substrings do not identify exactly one chunk: "
        f"{ambiguous}. A count of 0 makes the case unpassable; a count above 1 makes it "
        f"pass for the wrong reason."
    )


def test_off_topic_cases_assert_a_distance_instead_of_a_chunk(fixture_data) -> None:  # noqa: ANN001
    # An off-topic case asserting a chunk would be self-contradictory: the point
    # is that no chunk should match.
    for case in fixture_data["cases"]:
        if case["kind"] != "off_topic":
            continue
        assert "expect_distance_above" in case
        assert "expect_chunk_containing" not in case
        assert case["expect_distance_above"] == fixture_data["off_topic_distance_threshold"]


def test_first_turns_have_no_history_and_a_frozen_query_equal_to_the_question(fixture_data) -> None:  # noqa: ANN001
    # The frozen query for a first turn must be the raw question: no history
    # means no rewrite, so any other value would encode behaviour the pipeline
    # does not have.
    for case in fixture_data["cases"]:
        if case["kind"] != "first_turn":
            continue
        assert case["history"] == []
        assert case["search_query"] == case["question"], case["id"]


def test_cases_with_history_have_paired_turns(fixture_data) -> None:  # noqa: ANN001
    # The runners seed history via append_exchange, which consumes user and
    # assistant messages in pairs; an odd tail would be silently dropped.
    for case in fixture_data["cases"]:
        history = case["history"]
        assert len(history) % 2 == 0, case["id"]
        for index, turn in enumerate(history):
            assert turn["role"] == ("user" if index % 2 == 0 else "assistant"), case["id"]


def test_every_case_documents_what_it_guards(fixture_data) -> None:  # noqa: ANN001
    # A case whose purpose is not written down gets deleted the first time it
    # fails inconveniently.
    for case in fixture_data["cases"]:
        assert case.get("guards", "").strip(), case["id"]


def test_the_set_covers_every_kind(fixture_data) -> None:  # noqa: ANN001
    kinds = {c["kind"] for c in fixture_data["cases"]}
    assert kinds == {
        "first_turn",
        "followup_reference",
        "followup_vague",
        "topic_shift",
        "off_topic",
    }
