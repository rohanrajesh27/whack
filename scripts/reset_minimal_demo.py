#!/usr/bin/env python3
"""Reset MongoDB business data: store _id=1, banana SKU _id=1, three lots ST1-I1-B#-### (e.g. ST1-I1-B1-334)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from demo_seed import seed_minimal_demo  # noqa: E402


def main() -> None:
    sid = seed_minimal_demo()
    print(f"Reset complete. Store _id={sid}: bananas only, three batches (see demo_seed).")


if __name__ == "__main__":
    main()
