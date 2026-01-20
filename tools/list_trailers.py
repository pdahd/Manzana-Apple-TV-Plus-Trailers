#!/usr/bin/env python3
# tools/list_trailers.py @ v0.1.0
#
# Purpose:
#   List trailers count (machine-readable) for a given Apple TV URL.
#
# Output:
#   - stdout: ONLY an integer count (e.g. 3)
#   - stderr: human-readable list of trailers (t0..tN)
#
# Notes:
#   AppleTVPlus.get_info() uses Manzana logger which prints to stdout by default.
#   We redirect Manzana's Rich Console to stderr to keep stdout clean for workflow capture.

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, List, Optional


# --- Make repo root importable ---
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _redirect_manzana_logs_to_stderr() -> None:
    try:
        from rich.console import Console
        import utils.logger as manzana_logger

        manzana_logger.cons = Console(file=sys.stderr)
    except Exception:
        pass


_redirect_manzana_logs_to_stderr()

try:
    from core.api.aptv import AppleTVPlus
except Exception as e:
    raise RuntimeError(
        "Unable to import Manzana modules. Run this script from repository root, "
        "or ensure repo is on PYTHONPATH."
    ) from e


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    eprint(f"[list_trailers] ERROR: {msg}")
    raise SystemExit(code)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="List trailer count for an Apple TV page (stdout=count).")
    p.add_argument("--url", required=True, help="Apple TV page URL")
    p.add_argument("--default-only", action="store_true", help="Use Manzana --default logic (default background video)")
    args = p.parse_args(argv)

    atvp = AppleTVPlus()
    trailers = atvp.get_info(args.url, bool(args.default_only))

    if trailers is None:
        die("No response (trailers is None).")

    if not isinstance(trailers, list):
        die("Unexpected response type (trailers is not a list).")

    # Log a simple list to stderr (for human debugging)
    eprint(f"[list_trailers] default_only={bool(args.default_only)} count={len(trailers)}")
    for i, t in enumerate(trailers):
        title = str(t.get("title") or "")
        video_title = str(t.get("videoTitle") or "")
        eprint(f"[list_trailers] t{i}: {title} | {video_title}")

    # Machine-readable: ONLY print count to stdout
    print(len(trailers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
