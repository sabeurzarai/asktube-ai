"""The broad-question heuristic.

A pure function, so these tests need no database, no key and no event loop.
That is the point: an LLM classifier here would be non-deterministic, would add
latency to every request, and would break the documented guarantee that a first
turn makes no model call.
"""

import unicodedata

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
    # Phrasings a reviewer found missing. Each is as broad as the ones above -
    # they were absent only because nobody had listed them, which is exactly the
    # failure mode a hand-written pattern list has.
    "Wovon handelt das Video?",
    "Um was geht's im Video?",
    "Was ist der Inhalt des Videos?",
    "Worüber geht es?",
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
    # The German near-misses for the phrasings added above: same opening words,
    # but each asks about one thing inside the video rather than the whole of it.
    "Wovon handelt die dritte Schleife?",
    "Was ist der Inhalt der Liste?",
    "Um was geht's bei der for-Schleife?",
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


@pytest.mark.parametrize(
    "message", ["Worüber geht es im Video?", "Gib mir einen Überblick"]
)
def test_decomposed_umlauts_are_recognised_too(message: str) -> None:
    """The same question in NFD must classify the same as in NFC.

    An umlaut has two Unicode spellings: one code point (NFC, what a German
    keyboard produces) or a bare vowel plus a combining diaeresis (NFD, which
    macOS filesystems and some clipboard paths hand over). _normalise strips
    anything outside its allowlist, and a lone combining mark is outside it - so
    in NFD "Worüber" became "woru ber" and every German pattern missed. The
    fallthrough is silent: the question would simply be answered by retrieval,
    which is why nothing surfaced it until someone looked.
    """
    assert unicodedata.normalize("NFD", message) != message, (
        "this test is only meaningful if the NFD form actually differs"
    )

    assert is_broad_question(unicodedata.normalize("NFD", message)) is True
