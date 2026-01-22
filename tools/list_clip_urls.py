#!/usr/bin/env python3
# tools/list_clip_urls.py @ v0.1.2
#
# Purpose:
#   Extract clip URLs from a movie page (HTML) as a fallback for "trailer=all"
#   when the UTS API only returns 0/1 trailer.
#
# Output:
#   - stdout: clip URLs only (one per line)  [workflow-safe]
#   - stderr: debug + optional resolved titles (human readable)
#
# v0.1.2 changes vs v0.1.1:
# - --resolve-titles now resolves via CLIP HTML first (quiet, avoids API 500 noise).
# - Add --resolve-titles-api-fallback:
#     If HTML title cannot be resolved, then try AppleTVPlus.get_info(clip_url).
# - Keep stdout clean (URLs only). All logs go to stderr.

from __future__ import annotations

import argparse
import html as html_mod
import os
import re
import sys
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests


# --- Make repo root importable ---
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _redirect_manzana_logs_to_stderr() -> None:
    # If we ever call Manzana modules, keep their rich logs off stdout.
    try:
        from rich.console import Console
        import utils.logger as manzana_logger

        manzana_logger.cons = Console(file=sys.stderr)
    except Exception:
        pass


_redirect_manzana_logs_to_stderr()


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
    if last.startswith("umc.cmc."):
        return last

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
        r = requests.get(url, headers=headers, timeout=30, verify=False)

    if r.status_code != 200:
        die(f"Failed to fetch HTML (status={r.status_code}).")

    return r.text


def _extract_clip_hrefs(html: str, base_url: str, movie_id: str) -> List[str]:
    hrefs = re.findall(r'href="([^"]+)"', html, flags=re.IGNORECASE)
    out: List[str] = []
    seen = set()

    for raw in hrefs:
        raw = html_mod.unescape(raw)

        if "/clip/" not in raw:
            continue
        if f"targetId={movie_id}" not in raw:
            continue
        if "targetType=Movie" not in raw:
            continue

        abs_url = urljoin(base_url, raw).strip()

        if abs_url not in seen:
            seen.add(abs_url)
            out.append(abs_url)

    return out


def _clean_title(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    # Common title suffixes
    for suf in (" - Apple TV+", " - Apple TV", " | Apple TV+", " | Apple TV"):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return s


def _resolve_title_via_html(clip_url: str) -> Optional[str]:
    """
    Best-effort: fetch clip HTML and read og:title / <title>.
    Returns a single display string (prefer og:title), else None.
    """
    try:
        html = _fetch_html(clip_url)
    except Exception:
        return None

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")

        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            s = _clean_title(str(og.get("content")))
            if s:
                return s

        tit = soup.find("title")
        if tit and tit.text:
            s = _clean_title(str(tit.text))
            if s:
                return s
    except Exception:
        return None

    return None


def _resolve_title_via_api(clip_url: str) -> Optional[str]:
    """
    Best-effort: use AppleTVPlus.get_info(clip_url) to read videoTitle/title.
    This can be noisy (API 500 fallback etc), so it is optional.
    """
    try:
        from core.api.aptv import AppleTVPlus  # imported only when needed

        atvp = AppleTVPlus()
        items = atvp.get_info(clip_url, default=False)
        if not items or not isinstance(items, list):
            return None
        it = items[0] or {}
        vt = _clean_title(str(it.get("videoTitle") or ""))
        t = _clean_title(str(it.get("title") or ""))
        return vt or t or None
    except Exception:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="List clip URLs for a movie page (stdout = urls, one per line).")
    p.add_argument("--url", required=True, help="Apple TV movie page URL")
    p.add_argument(
        "--default-only",
        action="store_true",
        help="If set, treat as only default content (no clip fallback needed).",
    )
    p.add_argument(
        "--resolve-titles",
        action="store_true",
        help="Resolve each clip's name and print to stderr (stdout still URLs only).",
    )
    p.add_argument(
        "--resolve-titles-api-fallback",
        action="store_true",
        help="When --resolve-titles is enabled and HTML title cannot be resolved, try API fallback (may be noisy).",
    )
    args = p.parse_args(argv)

    if args.default_only:
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

    if args.resolve_titles and clips:
        for i, clip_url in enumerate(clips):
            name = _resolve_title_via_html(clip_url)

            if (not name) and args.resolve_titles_api_fallback:
                name = _resolve_title_via_api(clip_url)

            if name:
                eprint(f"[list_clip_urls] name[{i}]: {name}")
            else:
                eprint(f"[list_clip_urls] name[{i}]: (unresolved)")

    # stdout: URLs only
    for c in clips:
        print(c)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
