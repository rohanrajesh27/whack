"""
Banana ripeness classifier (BLIP-based, fully local).

Takes a PIL image, runs two BLIP captioning passes (one color-focused,
one state-focused), then maps the combined caption to a 1-5 ripeness
stage using weighted keyword scoring.

Scale:
    1 = unripe green
    2 = turning (yellow-green, still firm)
    3 = perfectly ripe yellow
    4 = very ripe with brown spots
    5 = overripe / rotten

Usage:
    from ripeness import classify_ripeness
    score, caption = classify_ripeness(pil_image)
"""

from __future__ import annotations

import torch
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration


# ── Model setup (loaded once on import) ─────────────────────────────────────

print("Loading ripeness model (BLIP)...")
_blip_processor = BlipProcessor.from_pretrained(
    "Salesforce/blip-image-captioning-base"
)
_blip_model = BlipForConditionalGeneration.from_pretrained(
    "Salesforce/blip-image-captioning-base"
)


# ── Captioning (two passes for more signal) ─────────────────────────────────

def generate_caption(image: Image.Image) -> str:
    """Two BLIP passes: one focused on color, one on overall state."""
    color_prompt = "the color of this banana is"
    inputs = _blip_processor(images=image, text=color_prompt, return_tensors="pt")
    with torch.no_grad():
        out = _blip_model.generate(**inputs, max_new_tokens=20)
    color_caption = _blip_processor.decode(out[0], skip_special_tokens=True)

    state_prompt = "this banana looks"
    inputs = _blip_processor(images=image, text=state_prompt, return_tensors="pt")
    with torch.no_grad():
        out = _blip_model.generate(**inputs, max_new_tokens=20)
    state_caption = _blip_processor.decode(out[0], skip_special_tokens=True)

    return f"{color_caption}. {state_caption}."


# ── Scoring (weighted keyword vote across all 5 stages) ─────────────────────

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
    """Map a caption to a 1-5 ripeness score via weighted keyword voting.

    Ties break toward the higher stage (more conservative for pricing).
    Defaults to 3 (ripe) if no keywords match.
    """
    text = caption.lower()
    scores = {stage: 0 for stage in _STAGE_KEYWORDS}
    for stage, keywords in _STAGE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[stage] += 1
    if sum(scores.values()) == 0:
        return 3
    return max(scores, key=lambda s: (scores[s], s))


# ── Public entry point ──────────────────────────────────────────────────────

def classify_ripeness(image: Image.Image) -> tuple[int, str]:
    """Full pipeline: image -> (ripeness_score, caption).

    Returns both so callers can reuse the caption for other things
    (e.g. product-name inference) without running BLIP twice.
    """
    caption = generate_caption(image)
    score = infer_ripeness_score(caption)
    return score, caption


# ── Standalone test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ripeness.py <path_to_banana_image>")
        sys.exit(1)

    img = Image.open(sys.argv[1])
    score, caption = classify_ripeness(img)

    print("=" * 50)
    print("  Banana Ripeness Classifier (BLIP)")
    print("=" * 50)
    print(f"  Image:    {sys.argv[1]}")
    print(f"  Caption:  {caption}")
    print(f"  Score:    {score} / 5")
    print("=" * 50)