#!/usr/bin/env python3
# tools/list_clip_urls.py @ v0.1.3
#
# Purpose:
#   Extract clip URLs from a movie page (HTML) as a fallback for "trailer=all"
#   when the UTS API only returns 0/1 trailer.
#
# Output:
#   - stdout: clip URLs only (one per line)  [workflow-safe]
#   - stderr: debug + optional resolved titles (human readable)
#
# v0.1.3 changes vs v0.1.2:
# - Fix mojibake (乱码) by decoding HTML robustly from r.content (UTF-8 first).
# - Improve --resolve-titles:
#     Prefer extracting clip title from serialized-server-data (JSON) on the clip page
#     (usually contains specific names like 吹替版/字幕版),
#     fallback to og:title / <title> only if JSON extraction fails.
# - Keep stdout clean (URLs only). All logs go to stderr.

from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
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


def _decode_html_response(r: requests.Response) -> str:
    """
    Robust HTML decoding to avoid mojibake:
    - Try UTF-8 strict first
    - Fallback to apparent_encoding (chardet/charset-normalizer) if available
    - Last resort: UTF-8 with replacement
    """
    raw = r.content or b""
    if not raw:
        return ""

    # 1) UTF-8 strict first (Apple pages are typically UTF-8)
    try:
        return raw.decode("utf-8")
    except Exception:
        pass

    # 2) apparent encoding fallback
    enc = None
    try:
        enc = (r.apparent_encoding or "").strip() or None
    except Exception:
        enc = None

    if enc:
        try:
            return raw.decode(enc, errors="strict")
        except Exception:
            try:
                return raw.decode(enc, errors="replace")
            except Exception:
                pass

    # 3) last resort
    return raw.decode("utf-8", errors="replace")


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

    return _decode_html_response(r)


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
    # Common suffixes on Apple pages
    for suf in (" - Apple TV+", " - Apple TV", " | Apple TV+", " | Apple TV"):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return s


def _deep_find_titles(obj: Any) -> List[str]:
    """
    Collect candidate titles from a nested JSON-like structure.
    Heuristics:
    - Prefer dicts under keys "playable" or in list "playables" that have a string "title"
    - Also collect any "title" fields, but later we will score/filter them.
    """
    titles: List[str] = []

    def walk(x: Any, parent_key: str = "") -> None:
        if isinstance(x, dict):
            # If it looks like a playable
            if parent_key in ("playable", "playables") and isinstance(x.get("title"), str):
                titles.append(x["title"])

            # Generic title fields
            if isinstance(x.get("title"), str):
                titles.append(x["title"])

            for k, v in x.items():
                walk(v, str(k))
        elif isinstance(x, list):
            for it in x:
                walk(it, parent_key)

    walk(obj)
    # Clean + unique (keep order)
    seen = set()
    out: List[str] = []
    for t in titles:
        tt = _clean_title(str(t))
        if not tt:
            continue
        if tt in seen:
            continue
        seen.add(tt)
        out.append(tt)
    return out


def _pick_best_title(candidates: List[str]) -> Optional[str]:
    """
    Pick a best title:
    - reject very generic ones that clearly include Apple TV branding
    - prefer titles that contain parentheses/keywords like 吹替/字幕 if present
    - otherwise prefer longer, non-generic titles
    """
    if not candidates:
        return None

    def score(t: str) -> Tuple[int, int]:
        # Higher is better
        bonus = 0

        # prefer “specific version” keywords
        for kw in ("吹替", "字幕", "吹き替え", "字幕版", "吹替版"):
            if kw in t:
                bonus += 50

        # prefer parentheses variants
        if ("(" in t and ")" in t) or ("（" in t and "）" in t):
            bonus += 20

        # penalize obvious generic branding
        if "Apple TV" in t or "AppleTV" in t:
            bonus -= 30

        # length as a weak signal (avoid tiny titles)
        return (bonus, len(t))

    best = sorted(candidates, key=score, reverse=True)[0]
    return best or None


def _extract_serialized_server_data(html: str) -> Optional[Any]:
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        s = soup.find("script", attrs={"type": "application/json", "id": "serialized-server-data"})
        if not s or not s.text:
            return None
        return json.loads(s.text)
    except Exception:
        return None


def _resolve_title_via_serialized_server_data(clip_url: str) -> Optional[str]:
    """
    Resolve clip name via serialized-server-data (preferred).
    """
    html = _fetch_html(clip_url)
    js = _extract_serialized_server_data(html)
    if js is None:
        return None

    cands = _deep_find_titles(js)
    return _pick_best_title(cands)


def _resolve_title_via_meta_title(clip_url: str) -> Optional[str]:
    """
    Fallback: og:title / <title> (often generic, may be identical across clips).
    """
    html = _fetch_html(clip_url)
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
    Optional last resort: call AppleTVPlus.get_info(clip_url) to read videoTitle/title.
    Can be noisy due to clips endpoint 500 fallback etc.
    """
    try:
        from core.api.aptv import AppleTVPlus

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
        help="If title cannot be resolved from HTML/serialized-server-data, try API fallback (may be noisy).",
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
            # Preferred: serialized-server-data (usually contains specific titles)
            name = _resolve_title_via_serialized_server_data(clip_url)

            # Fallback: og:title / <title>
            if not name:
                name = _resolve_title_via_meta_title(clip_url)

            # Optional: API fallback if still unresolved
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
