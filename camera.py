from __future__ import annotations

import os
import sys
from typing import Any

import cv2
import pytesseract  # Install using pip
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

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


def extract_text_from_image(image: Image.Image) -> str:
    # Use pytesseract to extract text from image
    return pytesseract.image_to_string(image)


def main() -> None:
    frame = capture_frame()
    pil_image = frame_to_pil(frame)
    text = extract_text_from_image(pil_image)
    print("\n--- Extracted text ---\n")
    print(text)


if __name__ == "__main__":
    main()
