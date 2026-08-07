"""Classifying a question as broad, without a model call.

A broad question asks about the whole video ("what is this video about?") rather
than a passage. Top-k retrieval answers those badly by construction, so they take
a different path.

This is a pure pattern match on purpose. An LLM classifier would be
non-deterministic, would add a call to every request including first turns - which
are documented and tested to make no model call - and would put a new failure
source on the answer path. The cost is that only phrasings someone thought of are
recognised; anything else falls through to the retrieval path, which is exactly
today's behaviour, so a miss is never a regression.
"""

import re

# fullmatch, not search: "what is this video about loops" is a PASSAGE question
# and must not be caught by the "what is this video about" pattern. Requiring the
# whole message to match is what separates the two, and it holds because broad
# questions are short by nature.
_BROAD_PATTERNS = [
    r"what(?:'s| is| are) (?:this |the )?video about",
    r"what(?:'s| is) it about",
    r"what (?:is|are) the (?:main |key )?(?:points?|topics?|takeaways?)",
    r"what does (?:this |the )?video (?:cover|discuss|talk about)",
    r"(?:can you )?(?:give me |tell me )?(?:a |an )?(?:short |brief |quick )?"
    r"(?:summary|overview)(?: of (?:this |the )?video)?",
    r"summari[sz]e(?: (?:this|the) video)?",
    r"tl ?dr",
    # German
    r"wor(?:um|ueber|über) geht(?:'s| es)(?: (?:in dem|im|in diesem) video)?",
    r"was behandelt (?:das|dieses) video",
    r"(?:gib mir )?(?:eine )?(?:kurze )?zusammenfassung(?: (?:des|vom) videos?)?",
    r"fass(?:e)? (?:das|dieses) video zusammen",
    r"(?:gib mir )?(?:einen )?(?:kurzen )?(?:ueberblick|überblick)(?: ueber das video| über das video)?",
    r"was sind die (?:haupt)?(?:themen|punkte)",
]

_COMPILED = [re.compile(pattern) for pattern in _BROAD_PATTERNS]


def _normalise(message: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Apostrophes survive so "what's" stays one token; umlauts survive so the
    German patterns match without the caller transliterating.
    """
    lowered = message.lower().strip()
    cleaned = re.sub(r"[^a-z0-9äöüß' ]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_broad_question(message: str) -> bool:
    """True when the message asks about the video as a whole."""
    normalised = _normalise(message)
    if not normalised:
        return False

    return any(pattern.fullmatch(normalised) for pattern in _COMPILED)
