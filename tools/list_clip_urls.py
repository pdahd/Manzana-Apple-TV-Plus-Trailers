#!/usr/bin/env python3
# tools/list_clip_urls.py @ v0.1.1
#
# v0.1.1 changes:
# - Add --resolve-titles:
#     Resolve each clip's (title, videoTitle) and print to stderr so Actions logs
#     show human-readable names (e.g. 吹替版 / 字幕版) during clip fallback.
#   stdout remains URLs only (one per line) to keep workflow capture clean.
# - Redirect Manzana Rich Console logs to stderr (avoid stdout pollution).

from __future__ import annotations

import argparse
import html as html_mod
import os
import re
import sys
from typing import Any, List, Optional
from urllib.parse import urlparse, urljoin

import requests


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


def _resolve_title_via_api(atvp, clip_url: str) -> Optional[tuple[str, str]]:
    """
    Try to resolve (title, videoTitle) via core/api/aptv.py.
    Returns None if failed.
    """
    try:
        items = atvp.get_info(clip_url, default=False)
        if not items or not isinstance(items, list):
            return None
        it = items[0] or {}
        t = str(it.get("title") or "").strip()
        vt = str(it.get("videoTitle") or "").strip()
        if t or vt:
            return (t, vt)
        return None
    except Exception:
        return None


def _resolve_title_via_html(clip_url: str) -> Optional[tuple[str, str]]:
    """
    Best-effort: fetch clip HTML and read og:title / <title>.
    Usually looks like: "GODZILLA ゴジラ(字幕版) - Apple TV+"
    We'll return ("" , og_title_or_title) if found.
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
            s = str(og.get("content")).strip()
            if s:
                return ("", s)

        tit = soup.find("title")
        if tit and tit.text:
            s = str(tit.text).strip()
            if s:
                return ("", s)
    except Exception:
        return None

    return None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="List clip URLs for a movie page (stdout = urls, one per line).")
    p.add_argument("--url", required=True, help="Apple TV movie page URL")
    p.add_argument("--default-only", action="store_true", help="If set, treat as only default content (no clip fallback needed).")
    p.add_argument(
        "--resolve-titles",
        action="store_true",
        help="Resolve each clip's title/videoTitle and print to stderr (stdout still URLs only).",
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

    # Optional: resolve titles for better logs
    if args.resolve_titles and clips:
        try:
            from core.api.aptv import AppleTVPlus
            atvp = AppleTVPlus()
        except Exception:
            atvp = None

        for i, clip_url in enumerate(clips):
            title = ""
            video_title = ""

            if atvp is not None:
                got = _resolve_title_via_api(atvp, clip_url)
                if got:
                    title, video_title = got

            if (not title and not video_title):
                got2 = _resolve_title_via_html(clip_url)
                if got2:
                    title, video_title = got2

            if title or video_title:
                # Prefer showing videoTitle (it usually contains 吹替版/字幕版)
                show = video_title or title
                eprint(f"[list_clip_urls] name[{i}]: {show}")
            else:
                eprint(f"[list_clip_urls] name[{i}]: (unresolved)")

    # stdout: one URL per line (clean)
    for c in clips:
        print(c)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
