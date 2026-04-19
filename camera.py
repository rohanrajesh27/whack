"""
Capture a photo from the default camera and extract visible text using Google Gemini.

Setup:
  pip install -r requirements.txt
  Add to .env: GEMINI_API_KEY=your_key

Run:
  python camera.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

import cv2
import google.generativeai as genai
from dotenv import load_dotenv
from PIL import Image

load_dotenv()


def configure_gemini() -> genai.GenerativeModel:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY in environment or .env file.", file=sys.stderr)
        sys.exit(1)
    genai.configure(api_key=api_key)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    return genai.GenerativeModel(model_name)


def capture_frame() -> Any:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Could not open camera (index 0).", file=sys.stderr)
        sys.exit(1)

    print("Camera on. Press SPACE to capture text, Q to quit.")
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


def extract_text(model: genai.GenerativeModel, image: Image.Image) -> str:
    prompt = (
        "Extract all readable text from this image. "
        "Preserve line breaks where they matter for readability. "
        "If there is no text, say so briefly."
    )
    response = model.generate_content([prompt, image])
    if not response.text:
        if getattr(response, "prompt_feedback", None):
            print(response.prompt_feedback, file=sys.stderr)
        print(
            "Gemini returned no text (check API key, model name, or safety filters).",
            file=sys.stderr,
        )
        sys.exit(1)
    return response.text.strip()


def main() -> None:
    model = configure_gemini()
    frame = capture_frame()
    pil_image = frame_to_pil(frame)
    text = extract_text(model, pil_image)
    print("\n--- Extracted text ---\n")
    print(text)


if __name__ == "__main__":
    main()
