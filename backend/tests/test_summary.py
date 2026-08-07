"""Pure helpers for the summarisation path.

All synchronous, no service construction, no key: transcript rebuilding and
timestamp validation are the parts most worth testing and the parts least
entangled with I/O.
"""

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


def test_extract_timestamps_reads_both_formats() -> None:
    text = "The intro is at 00:00, loops at 05:18, and a long one at 01:02:03."

    assert extract_timestamps(text) == [0.0, 318.0, 3723.0]


def test_extract_timestamps_ignores_plain_numbers() -> None:
    assert extract_timestamps("There are 5 topics and 30 examples.") == []


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
