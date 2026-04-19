#!/usr/bin/env python3
"""Reset MongoDB business data: one sample store, one banana SKU, three batches (ST#-I#-B#-###)."""

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
