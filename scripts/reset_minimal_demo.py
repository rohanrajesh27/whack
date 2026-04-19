#!/usr/bin/env python3
"""Reset MongoDB business data to a single store + minimal SKUs/batches (see demo_seed.MINIMAL_CATALOG)."""

import os
import sys

# Project root (parent of scripts/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from demo_seed import MINIMAL_CATALOG, seed_minimal_demo  # noqa: E402


def main() -> None:
    sid = seed_minimal_demo()
    n = len(MINIMAL_CATALOG)
    print(f"Reset complete. Single store _id={sid} with {n} product types and batches.")


if __name__ == "__main__":
    main()
