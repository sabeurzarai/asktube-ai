"""Pure helpers for the summarisation path.

All synchronous, no service construction, no key: transcript rebuilding and
timestamp validation are the parts most worth testing and the parts least
entangled with I/O.
"""

import pytest

from app.schemas.chunks import TranscriptChunk
from app.services.summary import (
    citations_for_timestamps,
    extract_timestamps,
    rebuild_transcript,
)


def make_chunk(index: int, text: str, start: float, end: float, segments: list[int]) -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id=f"vid-{index}",
        index=index,
        video_id="vid",
        text=text,
        start_seconds=start,
        end_seconds=end,
        segment_indices=segments,
        token_estimate=5,
        metadata={"source": "captions", "language": "en"},
    )


def test_rebuild_transcript_prefixes_each_chunk_with_its_timestamp() -> None:
    chunks = [
        make_chunk(0, "first part", 0.0, 65.0, [0, 1]),
        make_chunk(1, "second part", 65.0, 130.0, [1, 2]),
    ]

    rebuilt = rebuild_transcript(chunks)

    assert rebuilt == "[00:00] first part\n[01:05] second part"


def test_rebuild_transcript_orders_by_index_not_insertion() -> None:
    chunks = [
        make_chunk(2, "third", 20.0, 30.0, [2]),
        make_chunk(0, "first", 0.0, 10.0, [0]),
        make_chunk(1, "second", 10.0, 20.0, [1]),
    ]

    assert rebuild_transcript(chunks) == "[00:00] first\n[00:10] second\n[00:20] third"


def test_rebuild_transcript_drops_a_fully_duplicated_chunk() -> None:
    # A chunk whose segments are ALL already covered contributes nothing. The
    # one-segment boundary overlap is NOT removed - see the module docstring.
    chunks = [
        make_chunk(0, "the content", 0.0, 10.0, [0, 1]),
        make_chunk(1, "the content again", 0.0, 10.0, [0, 1]),
    ]

    assert rebuild_transcript(chunks) == "[00:00] the content"


def test_rebuild_transcript_of_nothing_is_empty() -> None:
    assert rebuild_transcript([]) == ""


def test_rebuild_transcript_switches_to_hours_past_the_hour_mark() -> None:
    """Past 60 minutes the label grows a third field, and the prompt says so.

    SUMMARY_PROMPT describes the transcript it is handed. It used to promise
    "[MM:SS] form" unconditionally, which is simply untrue for any video over an
    hour - format_timestamp emits [01:00:05] there. The model was then told to
    copy labels EXACTLY while being given a description that did not match what
    it could see, and the mismatch grows precisely for long videos, where a
    summary is worth the most.

    This test exists so the prompt's claim is checkable rather than asserted:
    if format_timestamp's format ever changes, this fails and the prompt text
    has to be revisited with it.
    """
    chunks = [
        make_chunk(0, "before the hour", 3599.0, 3600.0, [0]),
        make_chunk(1, "after the hour", 3605.0, 3700.0, [1]),
    ]

    assert rebuild_transcript(chunks) == "[59:59] before the hour\n[01:00:05] after the hour"


def test_extract_timestamps_reads_both_formats() -> None:
    text = "The intro is at 00:00, loops at 05:18, and a long one at 01:02:03."

    assert extract_timestamps(text) == [0.0, 318.0, 3723.0]


def test_extract_timestamps_ignores_plain_numbers() -> None:
    assert extract_timestamps("There are 5 topics and 30 examples.") == []


@pytest.mark.parametrize(
    "text",
    [
        "note 112:34 x",  # three leading digits - not MM:SS
        "id 10530:12 here",
        "reference 12:345 x",  # three trailing digits
        # This one holds for a STRUCTURAL reason rather than because of the
        # anchors - "3:4" has a one-digit seconds field, which (\d{2}) rejects
        # either way. Kept as documentation, not as a guard: it is the only case
        # here that stays green when both anchors are deleted.
        "version 1:2:3:4",
    ],
)
def test_extract_timestamps_will_not_cut_into_a_longer_digit_run(text: str) -> None:
    """The \\b anchors in _TIMESTAMP_RE were load-bearing but unasserted.

    Without them the pattern happily matches a SUBSTRING of a longer number:
    "112:34" would yield the "12:34" inside it, and the summary would grow a
    citation out of an identifier. Every other test in this file uses timestamps
    that stand alone, so deleting both anchors left the suite green - which is
    the definition of an untested guard.
    """
    assert extract_timestamps(text) == []


def test_citations_keep_only_timestamps_inside_the_video() -> None:
    chunks = [
        make_chunk(0, "first", 0.0, 60.0, [0]),
        make_chunk(1, "second", 60.0, 120.0, [1]),
    ]

    # 30s is in chunk 0, 90s in chunk 1, 9999s is invented.
    citations = citations_for_timestamps([30.0, 90.0, 9999.0], chunks)

    assert [c.chunk_id for c in citations] == ["vid-0", "vid-1"]
    assert citations[0].timestamp == "00:00-01:00"


def test_citations_deduplicate_repeated_chunks() -> None:
    chunks = [make_chunk(0, "first", 0.0, 60.0, [0])]

    # Two marks landing in the same chunk must not produce two citations.
    assert len(citations_for_timestamps([10.0, 20.0], chunks)) == 1


def test_citations_of_nothing_is_empty() -> None:
    assert citations_for_timestamps([12.0], []) == []


def test_a_tie_on_the_displayed_second_goes_to_the_earlier_chunk() -> None:
    """Two chunks can display the SAME label, and one of them has to win.

    format_timestamp truncates to whole seconds, so chunks starting at 60.2s and
    60.8s both render as "01:00". A model copying that label gives no way to tell
    which section it meant - the information needed to disambiguate was destroyed
    when the label was written, not when it was read.

    The resolution is to take the earlier chunk, which falls out of sorting by
    start_seconds and taking the first match. That is a deliberate choice rather
    than an accident of iteration order: the earlier chunk is the one whose label
    the model saw first in the rebuilt transcript, so it is the likelier referent.
    Pinned here because nothing else asserts it, and a switch to `min(...)` on
    some other key would silently change which source gets cited.
    """
    chunks = [
        make_chunk(0, "earlier", 60.2, 90.0, [0]),
        make_chunk(1, "later", 60.8, 120.0, [1]),
    ]

    citations = citations_for_timestamps([60.0], chunks)

    assert [c.chunk_id for c in citations] == ["vid-0"]
    assert citations[0].text == "earlier"


def test_citations_match_a_fractional_chunk_start_by_displayed_label() -> None:
    # chunk.start_seconds=70.56 displays as "01:10" (format_timestamp truncates).
    # A model copying that label writes "01:10", which extract_timestamps parses
    # back to 70.0 - not 70.56. Plain range containment (70.56 <= 70.0) is False,
    # so this only passes when the exact-display match runs first.
    chunks = [make_chunk(0, "content", 70.56, 130.0, [0])]

    citations = citations_for_timestamps([70.0], chunks)

    assert [c.chunk_id for c in citations] == ["vid-0"]


def test_citations_prefer_exact_display_match_over_overlapping_range() -> None:
    # Chunks overlap by one segment: chunk A spans 0.16-74.0 (displays "00:00")
    # and chunk B spans 70.56-130.0 (displays "01:10"). The mark 70.0 ("01:10")
    # falls inside BOTH ranges, but it was copied from B's label, so it must
    # cite B - not A, which plain range containment would pick first.
    chunks = [
        make_chunk(0, "a content", 0.16, 74.0, [0, 1]),
        make_chunk(1, "b content", 70.56, 130.0, [1, 2]),
    ]

    citations = citations_for_timestamps([70.0], chunks)

    assert [c.chunk_id for c in citations] == ["vid-1"]
