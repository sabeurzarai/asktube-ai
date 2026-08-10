"""Building a whole-video summary and validating the timestamps it claims.

Everything here is pure. The service that calls it owns the model call and the
error handling; this module owns the text.

On deduplication: TranscriptChunk stores its text as one concatenated string
plus a list of segment indices - NOT per-segment text. So when chunk N covers
segments 10-20 and chunk N+1 covers 20-30, segment 20's words are inside both
strings and cannot be removed without the original segments. rebuild_transcript
therefore drops only chunks whose segments are ENTIRELY already seen, and the
one-segment boundary overlap remains: a few repeated words per boundary.

How much: summing the length of every segment that appears in more than one
chunk, over the length of the rebuilt transcript, gives 5.2% for fWjsdhR3z3c
and 10.4% for sQK3Yr4Sc_k at the current CHUNK_MAX_CHARS of 600 - and 2.7% /
5.5% at 1200, because halving the chunk size doubles the number of boundaries.
The method is stated because the figure is not reproducible without it: an
earlier review reported 9.1% / 13.4% by some other measure, and that number
should not be trusted over this one. Still immaterial to a summary either way:
it is repeated words at segment boundaries, not repeated ideas.

The design spec claims full dedup; it is wrong, and this is the correction.
"""

import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from app.schemas.chunks import TranscriptChunk
from app.schemas.rag import TimestampCitation
from app.services.rag_service import format_timestamp

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are AskTube AI. You are given a full video transcript in which "
                "every section is prefixed with its timestamp in square brackets - "
                "[MM:SS], or [HH:MM:SS] once the video passes an hour. "
                "Summarise what the video covers, as a short overview followed by the "
                "main points in the order they appear. "
                "Start every main point with the timestamp of the section it comes "
                "from, copied EXACTLY from the transcript - never invent or estimate a "
                "timestamp, and never use one that does not appear above. "
                "Use only what the transcript contains. Do not add outside knowledge."
            ),
        ),
        ("human", "Transcript:\n{transcript}\n\nUser question:\n{question}"),
    ]
)

# Matches 05:18 and 01:02:03. The leading \b stops it from cutting into a longer
# digit run, so "10530:12" is not read as a timestamp.
_TIMESTAMP_RE = re.compile(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b")


def rebuild_transcript(chunks: list[TranscriptChunk]) -> str:
    """One timestamped line per chunk, ordered by index."""
    lines: list[str] = []
    seen_segments: set[int] = set()

    for chunk in sorted(chunks, key=lambda item: item.index):
        if chunk.segment_indices and all(i in seen_segments for i in chunk.segment_indices):
            continue

        seen_segments.update(chunk.segment_indices)
        lines.append(f"[{format_timestamp(chunk.start_seconds)}] {chunk.text}")

    return "\n".join(lines)


def extract_timestamps(text: str) -> list[float]:
    """Every timestamp mentioned in the model's answer, as seconds."""
    seconds: list[float] = []

    for hours, minutes, secs in _TIMESTAMP_RE.findall(text):
        total = int(minutes) * 60 + int(secs)
        if hours:
            total += int(hours) * 3600
        seconds.append(float(total))

    return seconds


def citations_for_timestamps(
    timestamps: list[float],
    chunks: list[TranscriptChunk],
) -> list[TimestampCitation]:
    """Turn claimed timestamps into citations, dropping the ones that are not real.

    Matching happens in two steps, and the order matters:

    1. Exact display match. rebuild_transcript labels each chunk with
       format_timestamp(chunk.start_seconds), and SUMMARY_PROMPT tells the model
       to copy that label EXACTLY. format_timestamp TRUNCATES to whole seconds,
       so a chunk starting at 70.56s is shown as "01:10" - a model that complies
       writes "01:10", which extract_timestamps parses back to 70.0, not 70.56.
       Plain range containment (chunk.start_seconds <= 70.0) is then False for
       the very chunk that displayed the label, which is the defect this method
       fixes: comparing the claimed mark's OWN displayed form against each
       chunk's displayed form attributes it correctly regardless of truncation.
       It also resolves overlap correctly: chunks share one segment at each
       boundary (overlap_segments=1), so a later chunk's start can fall inside
       an earlier chunk's range, and range containment alone would credit the
       wrong chunk for a label that only the later one actually showed.
    2. Range containment, as a fallback, for marks the model took from inside a
       section rather than copied from its label - those never had a display
       match to begin with.

    Both steps take the FIRST match in start order, which decides the ties they
    can produce: two chunks starting at 60.2s and 60.8s display the same "01:00",
    and overlapping ranges can contain the same mark. The earlier chunk wins,
    because it is the one whose label appeared first in the rebuilt transcript
    and so is the likelier referent. The tie is not resolvable in principle -
    truncating to whole seconds destroyed the distinguishing information before
    the model ever saw it - so this is a defensible default, not a correct
    answer.

    A model can also emit a timestamp that exists nowhere in the video. Attaching
    a citation object to it would assert a source that does not exist, which is
    worse than having no citation at all - so an unmatched mark is logged and
    discarded.
    """
    if not chunks:
        return []

    ordered = sorted(chunks, key=lambda item: item.start_seconds)
    citations: list[TimestampCitation] = []
    seen_chunks: set[str] = set()

    for timestamp in timestamps:
        display = format_timestamp(timestamp)
        match = next(
            (c for c in ordered if format_timestamp(c.start_seconds) == display), None
        )
        if match is None:
            match = next(
                (c for c in ordered if c.start_seconds <= timestamp <= c.end_seconds), None
            )
        if match is None:
            logger.warning(
                "Summary claimed timestamp %s, which matches no chunk of the video; "
                "dropping the citation.",
                format_timestamp(timestamp),
            )
            continue

        if match.chunk_id in seen_chunks:
            continue

        seen_chunks.add(match.chunk_id)
        citations.append(
            TimestampCitation(
                chunk_id=match.chunk_id,
                video_id=match.video_id,
                start_seconds=match.start_seconds,
                end_seconds=match.end_seconds,
                timestamp=(
                    f"{format_timestamp(match.start_seconds)}-"
                    f"{format_timestamp(match.end_seconds)}"
                ),
                text=match.text,
            )
        )

    return citations
