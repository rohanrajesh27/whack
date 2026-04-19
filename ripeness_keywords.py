"""Keyword ripeness scoring (no ML). Shared by camera.py and ripeness.py."""

from __future__ import annotations

_STAGE_KEYWORDS: dict[int, list[str]] = {
    1: [
        "green", "bright green", "unripe", "immature", "hard",
        "not ripe", "not yet ripe", "raw", "firm green",
    ],
    2: [
        "yellow-green", "green-yellow", "slightly green", "mostly green",
        "turning yellow", "almost ripe", "slightly unripe", "firm yellow",
    ],
    3: [
        "yellow", "bright yellow", "ripe", "ready to eat", "mature",
        "golden", "perfectly ripe", "fresh yellow",
    ],
    4: [
        "brown spots", "spotted", "freckled", "very ripe", "speckled",
        "brown spotted", "fully ripe", "sweet", "soft",
    ],
    5: [
        "brown", "black", "mushy", "overripe", "over-ripe", "over ripe",
        "rotten", "spoiled", "rotting", "decayed", "dark brown",
        "mostly brown", "too ripe", "bad",
    ],
}


def infer_ripeness_score(caption: str) -> int:
    """Map text (e.g. BLIP caption or ResNet label string) to 1–5 ripeness."""
    text = caption.lower()
    scores = {stage: 0 for stage in _STAGE_KEYWORDS}
    for stage, keywords in _STAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[stage] += 1
    if sum(scores.values()) == 0:
        return 3
    return max(scores, key=lambda s: (scores[s], s))
