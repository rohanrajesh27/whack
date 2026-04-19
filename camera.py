from __future__ import annotations

import os
import re
import sys
from typing import Any

import cv2
import pytesseract
import torch
from dotenv import load_dotenv
from PIL import Image
from transformers import (
    pipeline,
    BlipProcessor,
    BlipForConditionalGeneration,
)
from torchvision import models, transforms

load_dotenv()

# ── Model setup (loaded once at startup) ────────────────────────────────────

# 1. Image captioning (BLIP)
print("Loading captioning model (BLIP)...")
blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
blip_model     = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")

# 2. Object detection (DETR)
print("Loading object detection model (DETR)...")
detector = pipeline("object-detection", model="facebook/detr-resnet-50")

# 3. Image classification (ResNet-50 via torchvision)
print("Loading classification model (ResNet-50)...")
resnet = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
resnet.eval()
imagenet_labels: list[str] = models.ResNet50_Weights.IMAGENET1K_V1.meta["categories"]

resnet_transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(224),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])

# ── Camera capture ───────────────────────────────────────────────────────────

def capture_frame() -> Any:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Could not open camera (index 0).", file=sys.stderr)
        sys.exit(1)

    print("Camera on. Press SPACE to capture, Q to quit.")
    frame = None
    while True:
        ok, current = cap.read()
        if not ok:
            print("Failed to read from camera.", file=sys.stderr)
            break
        cv2.imshow("Capture (SPACE = grab, Q = quit)", current)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" "):
            frame = current.copy()
            break
        if key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    if frame is None:
        print("No frame captured.", file=sys.stderr)
        sys.exit(1)
    return frame


def frame_to_pil(frame: Any) -> Image.Image:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)

# ── Analysis functions ───────────────────────────────────────────────────────

def generate_caption(image: Image.Image) -> str:
    """Generate a natural-language caption using BLIP."""
    inputs = blip_processor(image, return_tensors="pt")
    with torch.no_grad():
        out = blip_model.generate(**inputs, max_new_tokens=60)
    return blip_processor.decode(out[0], skip_special_tokens=True)


def detect_objects(image: Image.Image) -> list[dict]:
    """Detect objects and their bounding boxes using DETR."""
    return detector(image)


def classify_image(image: Image.Image, top_k: int = 5) -> list[tuple[str, float]]:
    """Return the top-k ImageNet class predictions using ResNet-50."""
    tensor = resnet_transform(image).unsqueeze(0)
    with torch.no_grad():
        logits = resnet(tensor)
    probs  = torch.softmax(logits, dim=1)[0]
    top_k_probs, top_k_indices = torch.topk(probs, top_k)
    return [
        (imagenet_labels[idx.item()], round(prob.item() * 100, 2))
        for prob, idx in zip(top_k_probs, top_k_indices)
    ]


def extract_text(image: Image.Image) -> str:
    """Run Tesseract OCR with optimised config for product labels."""
    custom_config = r"--oem 3 --psm 11"   # sparse text mode — good for labels
    return pytesseract.image_to_string(image, config=custom_config)


PRODUCT_CODE_PATTERN = re.compile(
    r"\b([A-Z]{2}[#\d]-\d{2}-[A-Z]\d-\d{3})\b"
)

def extract_product_code(raw_text: str) -> str | None:
    """
    Search OCR output for a code matching XX#-##-X#-###.

    X  = any uppercase letter
    #  = any digit
    Pattern: [A-Z][A-Z][digit] - [digit][digit] - [A-Z][digit] - [digit][digit][digit]
    Example: AB3-45-C6-789
    """
    # Tesseract sometimes confuses O↔0, I↔1, S↔5 — normalise first
    normalised = (
        raw_text
        .replace("O", "0")   # letter O  → zero
        .replace("I", "1")   # letter I  → one
        .replace("S", "5")   # letter S  → five  (optional — remove if unwanted)
        .upper()
    )

    # Strict pattern: XX#-##-X#-###
    strict = re.compile(r"\b([A-Z]{2}\d-\d{2}-[A-Z]\d-\d{3})\b")
    match  = strict.search(normalised)
    if match:
        return match.group(1)

    # Fuzzy fallback — accept common OCR noise characters (space/dot instead of dash)
    fuzzy = re.compile(r"([A-Z]{2}\d)[^A-Z0-9](\d{2})[^A-Z0-9]([A-Z]\d)[^A-Z0-9](\d{3})")
    match = fuzzy.search(normalised)
    if match:
        return "-".join(match.groups())

    return None


def format_analysis_report(
    caption:      str,
    objects:      list[dict],
    top_classes:  list[tuple[str, float]],
    raw_text:     str,
    product_code: str | None,
) -> str:
    """Assemble a human-readable analysis report."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("           FULL IMAGE ANALYSIS REPORT")
    lines.append("=" * 60)

    # ── Caption ──────────────────────────────────────────────────
    lines.append("\n[1] SCENE DESCRIPTION (BLIP captioning)")
    lines.append("-" * 40)
    lines.append(f"  {caption}")

    # ── Classification ────────────────────────────────────────────
    lines.append("\n[2] TOP IMAGE CLASSIFICATIONS (ResNet-50 / ImageNet)")
    lines.append("-" * 40)
    for rank, (label, pct) in enumerate(top_classes, 1):
        lines.append(f"  {rank}. {label:<30} {pct:>6.2f}%")

    # ── Object detection ──────────────────────────────────────────
    lines.append("\n[3] DETECTED OBJECTS (DETR)")
    lines.append("-" * 40)
    if objects:
        seen: dict[str, float] = {}
        for obj in objects:
            label = obj["label"]
            score = round(obj["score"] * 100, 1)
            # Keep highest-confidence instance per label
            if label not in seen or score > seen[label]:
                seen[label] = score
        for label, score in sorted(seen.items(), key=lambda x: -x[1]):
            lines.append(f"  • {label:<28} confidence: {score:.1f}%")
    else:
        lines.append("  No objects detected.")

    # ── OCR ───────────────────────────────────────────────────────
    lines.append("\n[4] EXTRACTED TEXT (Tesseract OCR)")
    lines.append("-" * 40)
    cleaned = raw_text.strip()
    lines.append(cleaned if cleaned else "  (no text detected)")

    # ── Product code ──────────────────────────────────────────────
    lines.append("\n[5] PRODUCT CODE  (format: XX#-##-X#-###)")
    lines.append("-" * 40)
    if product_code:
        lines.append(f"  ✔  Found: {product_code}")
    else:
        lines.append("  ✘  No matching product code found in OCR output.")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)

# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    frame    = capture_frame()
    pil_img  = frame_to_pil(frame)

    print("\nRunning analysis — please wait...\n")

    caption      = generate_caption(pil_img)
    objects      = detect_objects(pil_img)
    top_classes  = classify_image(pil_img, top_k=5)
    raw_text     = extract_text(pil_img)
    product_code = extract_product_code(raw_text)

    report = format_analysis_report(
        caption, objects, top_classes, raw_text, product_code
    )
    print(report)


if __name__ == "__main__":
    main()
