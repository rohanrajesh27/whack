from __future__ import annotations

import os
import re
import sys
from typing import Any
import numpy as np

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

# COCO class names (lowercase) that we treat as grocery / supermarket items for DETR.
GROCERY_COCO_LABELS: frozenset[str] = frozenset({
    "banana",
    "apple",
    "orange",
    "broccoli",
    "carrot",
    "sandwich",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "bottle",
    "wine glass",
    "cup",
    "bowl",
    "fork",
    "knife",
    "spoon",
})

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

def capture_frame(prompt: str = "Capture") -> Any:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Could not open camera (index 0).", file=sys.stderr)
        sys.exit(1)

    print(f"{prompt}\nPress SPACE to capture, Q to quit.")
    frame = None
    while True:
        ok, current = cap.read()
        if not ok:
            print("Failed to read from camera.", file=sys.stderr)
            break
        cv2.imshow(f"{prompt} (SPACE = grab, Q = quit)", current)
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
    """Generate a grocery-focused caption and ripeness estimate using BLIP."""
    prompt = "Describe the object in the image as a grocery product and name it specifically, including ripeness." 
    inputs = blip_processor(images=image, text=prompt, return_tensors="pt")
    with torch.no_grad():
        out = blip_model.generate(**inputs, max_new_tokens=60)
    return blip_processor.decode(out[0], skip_special_tokens=True)


def detect_objects(image: Image.Image) -> list[dict]:
    """Detect objects and their bounding boxes using DETR."""
    return detector(image)


def best_grocery_detection(objects: list[dict]) -> dict | None:
    """Highest-confidence detection whose label is a grocery-related COCO class."""
    grocery_hits = [
        o for o in objects if str(o.get("label", "")).lower() in GROCERY_COCO_LABELS
    ]
    if not grocery_hits:
        return None
    return max(grocery_hits, key=lambda o: float(o.get("score", 0.0)))


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


def infer_product_name(
    caption: str,
    objects: list[dict],
    top_classes: list[tuple[str, float]],
) -> str:
    """Infer a likely grocery product name from the caption, detected objects, and classification labels."""
    caption_lower = caption.lower()
    grocery_items = [
        "banana",
        "apple",
        "orange",
        "avocado",
        "tomato",
        "lettuce",
        "cucumber",
        "strawberry",
        "grape",
        "pear",
        "peach",
        "mango",
        "pineapple",
        "broccoli",
        "carrot",
    ]

    primary = best_grocery_detection(objects)
    if primary is not None:
        raw_label = str(primary["label"]).strip()
        return raw_label.title() if raw_label else "Unknown product"

    for item in grocery_items:
        if item in caption_lower:
            return item.title()

    if top_classes:
        top_label = top_classes[0][0].lower()
        for item in grocery_items:
            if item in top_label:
                return item.title()
        return top_label.title()

    return "Unknown product"

def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Clean up a phone photo before sending it to Tesseract."""
    # PIL -> OpenCV array
    img = np.array(image)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # 1. Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. Upscale — Tesseract likes text at least 30px tall
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    # 3. Denoise (removes camera grain without softening edges too much)
    gray = cv2.fastNlMeansDenoising(gray, h=10)

    # 4. Adaptive threshold — handles uneven lighting way better than a fixed threshold
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,   # block size — try 21, 31, 41
        10,   # constant subtracted from the mean
    )

    # 5. Small morphological open to kill speckle
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    return Image.fromarray(binary)


def infer_ripeness_score(caption: str) -> int:
    """Map a grocery caption to a ripeness score from 1 (unripe) to 5 (overripe)."""
    text = caption.lower()
    if any(word in text for word in ["overripe", "over-ripe", "mushy", "brown spots", "too ripe", "soft"]):
        return 5
    if any(word in text for word in ["very ripe", "ripe", "yellow", "soft", "ready to eat"]):
        return 4
    if any(word in text for word in ["ripe", "mature", "fresh", "ready"]):
        return 3
    if any(word in text for word in ["slightly unripe", "firm", "not ripe", "not yet ripe", "still green"]):
        return 2
    if any(word in text for word in ["unripe", "green", "hard", "immature", "raw"]):
        return 1
    return 3


def extract_text(image: Image.Image) -> str:
    """Run Tesseract OCR with optimised config for product labels."""
    prepped = preprocess_for_ocr(image)
    custom_config = r"--oem 3 --psm 11"
    return pytesseract.image_to_string(prepped, config=custom_config)


# Product code: ***-*#-*#-###  (* = alphanumeric, # = digit) after upper-casing OCR text.
PRODUCT_CODE_STRICT = re.compile(r"\b([A-Z0-9]{3}-[A-Z0-9]\d-[A-Z0-9]\d-\d{3})\b")
PRODUCT_CODE_FUZZY = re.compile(
    r"\b([A-Z0-9]{3})[^A-Z0-9]+([A-Z0-9]\d)[^A-Z0-9]+([A-Z0-9]\d)[^A-Z0-9]+(\d{3})\b"
)
PRODUCT_CODE_COMPACT = re.compile(r"([A-Z0-9]{3})([A-Z0-9]\d)([A-Z0-9]\d)(\d{3})")


def extract_product_code(raw_text: str) -> str | None:
    normalised = raw_text.upper().replace("I", "1")

    m = PRODUCT_CODE_STRICT.search(normalised)
    if m:
        return m.group(1)

    m = PRODUCT_CODE_FUZZY.search(normalised)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"

    compact = re.sub(r"[\s\-\._|/\\]+", "", normalised)
    m = PRODUCT_CODE_COMPACT.search(compact)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"

    return None


def format_analysis_report(
    caption:      str,
    ripeness:     int,
    objects:      list[dict],
    top_classes:  list[tuple[str, float]],
    raw_text:     str,
    product_code: str | None,
) -> str:
    """Assemble a human-readable analysis report."""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("           OBJECT + TEXT ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append("  Single capture: vision models + Tesseract OCR on the same frame")

    # ── Caption ──────────────────────────────────────────────────
    lines.append("\n[1] SCENE DESCRIPTION (BLIP captioning)")
    lines.append("-" * 40)
    lines.append(f"  {caption}")

    # ── Classification ────────────────────────────────────────────
    lines.append("\n[2] TOP IMAGE CLASSIFICATIONS (ResNet-50 / ImageNet)")
    lines.append("-" * 40)
    for rank, (label, pct) in enumerate(top_classes, 1):
        lines.append(f"  {rank}. {label:<30} {pct:>6.2f}%")

    lines.append("\n[3] GROCERY RIPENESS ASSESSMENT")
    lines.append("-" * 40)
    lines.append(f"  {ripeness} / 5")

    # ── Object detection ──────────────────────────────────────────
    lines.append("\n[4] DETECTED OBJECTS (DETR)")
    lines.append("-" * 40)
    primary = best_grocery_detection(objects)
    if primary is not None:
        pct = round(float(primary["score"]) * 100, 1)
        lines.append(
            f"  ★ Grocery pick (highest confidence): {primary['label']}  ({pct:.1f}%)"
        )
    elif objects:
        lines.append("  (No detections matched the grocery whitelist — see list below.)")
    if objects:
        seen: dict[str, float] = {}
        for obj in objects:
            label = obj["label"]
            score = round(obj["score"] * 100, 1)
            if label not in seen or score > seen[label]:
                seen[label] = score
        primary_label = primary["label"] if primary is not None else None
        for label, score in sorted(seen.items(), key=lambda x: -x[1]):
            tag = "★ " if primary_label is not None and label == primary_label else "  "
            lines.append(f"  {tag}{label:<26} confidence: {score:.1f}%")
    else:
        lines.append("  No objects detected.")

    # ── OCR ───────────────────────────────────────────────────────
    lines.append("\n[5] EXTRACTED TEXT (Tesseract OCR)")
    lines.append("-" * 40)
    cleaned = raw_text.strip()
    lines.append(cleaned if cleaned else "  (no text detected)")

    # ── Product code ──────────────────────────────────────────────
    lines.append("\n[6] PRODUCT CODE  (format: ***-*#-*#-###; * = alnum, # = digit)")
    lines.append("-" * 40)
    if product_code:
        lines.append(f"  ✔  Found: {product_code}")
    else:
        lines.append("  ✘  No matching product code found in OCR output.")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)

# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    frame = capture_frame("Capture: product + label in one shot (SPACE)")

    image = frame_to_pil(frame)

    print("\nRunning analysis — please wait...\n")

    caption      = generate_caption(image)
    objects      = detect_objects(image)
    top_classes  = classify_image(image, top_k=5)
    raw_text     = extract_text(image)
    product_code = extract_product_code(raw_text)

    product_name = infer_product_name(caption, objects, top_classes)
    ripeness_score = infer_ripeness_score(caption)

    report = format_analysis_report(
        caption, ripeness_score, objects, top_classes, raw_text, product_code
    )
    print(report)

    print(f"{product_name}, {ripeness_score}, {product_code or 'UNKNOWN'}")


if __name__ == "__main__":
    main()
