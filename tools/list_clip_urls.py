#!/usr/bin/env python3
# tools/list_clip_urls.py @ v0.1.0
#
# Purpose:
#   Extract clip URLs from a movie page (HTML) as a fallback for "trailer=all"
#   when the UTS API only returns 1 trailer (common on older pages / storefront mismatch).
#
# How it works:
#   - Derive movie content id from URL path: last segment like "umc.cmc.xxxxx"
#   - Download the movie page HTML
#   - Extract <a href="..."> values containing:
#       /clip/  AND  targetId=<movie_id>  AND  targetType=Movie
#   - Output one absolute URL per line to stdout (deduplicated, stable order)
#
# Output:
#   - stdout: clip URLs only (one per line)
#   - stderr: info/debug lines
#
# Notes:
#   - This does not currently distinguish "Trailers" vs "Bonus Content".
#     It returns all clip URLs found for that movie targetId in the HTML.

from __future__ import annotations

import argparse
import html as html_mod
import os
import re
import sys
from typing import Any, List, Optional
from urllib.parse import urlparse, urljoin

import requests


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    eprint(f"[list_clip_urls] ERROR: {msg}")
    raise SystemExit(code)


def _movie_id_from_url(url: str) -> str:
    u = urlparse(url)
    path = u.path.strip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        die("Unable to parse movie id from URL path (empty path).")

    last = parts[-1]
    # Typical: /be/movie/<slug>/umc.cmc.xxxxx
    if last.startswith("umc.cmc."):
        return last

    # Sometimes last segment may include something else; try to find the first umc.cmc.* from the end
    for p in reversed(parts):
        if p.startswith("umc.cmc."):
            return p

    die("Unable to find 'umc.cmc.*' content id in URL path.")


def _fetch_html(url: str) -> str:
    headers = {
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=30)
    except Exception:
        # fallback without SSL verify
        r = requests.get(url, headers=headers, timeout=30, verify=False)

    if r.status_code != 200:
        die(f"Failed to fetch HTML (status={r.status_code}).")

    return r.text


def _extract_clip_hrefs(html: str, base_url: str, movie_id: str) -> List[str]:
    """
    Extract href="..." values from HTML and filter clip URLs for this movie_id.
    """
    # Simple, robust-enough href extraction (works even without a full DOM parser)
    hrefs = re.findall(r'href="([^"]+)"', html, flags=re.IGNORECASE)
    out: List[str] = []
    seen = set()

    for raw in hrefs:
        raw = html_mod.unescape(raw)

        # Quick filter
        if "/clip/" not in raw:
            continue
        if f"targetId={movie_id}" not in raw:
            continue
        if "targetType=Movie" not in raw:
            continue

        abs_url = urljoin(base_url, raw)

        # Normalize: remove trailing spaces
        abs_url = abs_url.strip()

        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)

    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="List clip URLs for a movie page (stdout = urls, one per line).")
    p.add_argument("--url", required=True, help="Apple TV movie page URL")
    p.add_argument("--default-only", action="store_true", help="If set, treat as only default content (no clip fallback needed).")
    args = p.parse_args(argv)

    if args.default_only:
        # In default-only mode, caller usually wants only the default background video.
        # Returning no clips makes the workflow stay on API path / single item behavior.
        eprint("[list_clip_urls] default_only=true -> returning 0 clip urls")
        return 0

    url = args.url.strip()
    if not url:
        die("Empty url")

    movie_id = _movie_id_from_url(url)
    u = urlparse(url)
    base_url = f"{u.scheme}://{u.netloc}/"

    eprint(f"[list_clip_urls] movie_id={movie_id}")
    html = _fetch_html(url)

    clips = _extract_clip_hrefs(html, base_url=base_url, movie_id=movie_id)

    eprint(f"[list_clip_urls] found={len(clips)}")
    for i, c in enumerate(clips):
        eprint(f"[list_clip_urls] clip[{i}]: {c}")

    # stdout: one URL per line
    for c in clips:
        print(c)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
