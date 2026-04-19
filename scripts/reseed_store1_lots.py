#!/usr/bin/env python3
"""Recreate three banana lots (ST#-I#-B#-###) when only ``lots`` (and readings) were deleted."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from demo_seed import STORE_PILOT_ID, reseed_banana_lots_for_store  # noqa: E402


def main() -> None:
    ok = reseed_banana_lots_for_store(store_id=STORE_PILOT_ID)
    if ok:
        print(f"Re-seeded banana batches for store_id={STORE_PILOT_ID}.")
    else:
        print("No banana SKU found for that store; run scripts/reset_minimal_demo.py first.")


if __name__ == "__main__":
    main()
