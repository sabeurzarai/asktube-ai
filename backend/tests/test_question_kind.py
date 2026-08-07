"""The broad-question heuristic.

A pure function, so these tests need no database, no key and no event loop.
That is the point: an LLM classifier here would be non-deterministic, would add
latency to every request, and would break the documented guarantee that a first
turn makes no model call.
"""

import pytest

from app.services.question_kind import is_broad_question

BROAD = [
    "What is this video about?",
    "what's this video about",
    "What is it about?",
    "Summarize this video",
    "summarise the video",
    "Give me a summary",
    "give me a short overview of this video",
    "What are the main points?",
    "What does this video cover?",
    "tldr",
    # German - the app is used in German, so coverage is a decision, not an accident.
    "Worum geht es in dem Video?",
    "worum geht's",
    "Was behandelt dieses Video?",
    "Gib mir eine kurze Zusammenfassung",
    "Fasse das Video zusammen",
    "Gib mir einen Überblick",
]

NARROW = [
    "How do I do addition in Python?",
    "What does the video say about loops?",
    "give me an example of one",
    "What is the pass keyword for?",
    "and the next one?",
    "What is a vascular plant?",
    # The dangerous near-miss: contains "about" and names the video, but asks
    # about one topic. Matching this would send a passage question down the
    # summary path.
    "What is this video about loops?",
    "Summarize what the video says about the while loop",
]


@pytest.mark.parametrize("message", BROAD)
def test_broad_questions_are_recognised(message: str) -> None:
    assert is_broad_question(message) is True


@pytest.mark.parametrize("message", NARROW)
def test_narrow_questions_are_not_broad(message: str) -> None:
    assert is_broad_question(message) is False


def test_empty_and_whitespace_are_not_broad() -> None:
    assert is_broad_question("") is False
    assert is_broad_question("   ") is False
