#!/usr/bin/env python3
# tools/select_format.py @ v0.1.1
#
# Fix in v0.1.1:
#   Ensure stdout is clean (ONLY the final effective format string).
#   Manzana's internal logger prints INFO lines via Rich Console to stdout by default.
#   We redirect Manzana's Rich Console to stderr so workflow can safely capture stdout.
#
# Output:
#   - stdout: ONLY the effective format string (e.g. v6+a0+s4) or "" (custom empty)
#   - stderr: selection explanation + Manzana INFO logs

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# --- Make repo root importable ---
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _redirect_manzana_logs_to_stderr() -> None:
    """
    Manzana uses utils/logger.py which prints via a module-level Rich Console `cons`
    defaulting to stdout. That pollutes stdout when this selector is captured by bash.

    We redirect that console to stderr, so:
      - selector stdout remains only the final format string
      - logs still appear in Actions logs (stderr)
    """
    try:
        from rich.console import Console
        import utils.logger as manzana_logger

        # Replace Console to print to stderr
        manzana_logger.cons = Console(file=sys.stderr)
    except Exception:
        # If rich or module not available, do nothing.
        pass


# Redirect as early as possible (safe even if used in custom mode)
_redirect_manzana_logs_to_stderr()


try:
    from core.api.aptv import AppleTVPlus
    from core.api.hls import get_hls
except Exception as e:
    raise RuntimeError(
        "Unable to import Manzana modules. Run this script from repository root, "
        "or ensure repo is on PYTHONPATH."
    ) from e


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def die(msg: str, code: int = 2) -> None:
    eprint(f"[selector] ERROR: {msg}")
    raise SystemExit(code)


def _parse_trailer_arg(trailer: str) -> int:
    """
    Accept: t0, t1, ... or 0,1,2...
    Reject: all/a (preset mode v0.1.x does not support trailer=all)
    """
    t = (trailer or "").strip().lower()
    if t in ("all", "a"):
        die("trailer=all is not supported in preset modes (v0.1.x). Use t0/t1/...")
    if t.startswith("t"):
        t = t[1:]
    if not t.isdigit():
        die(f"Invalid trailer value '{trailer}'. Expected t0/t1/... or numeric index.")
    return int(t)


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _parse_bitrate_to_bps(bitrate: Any) -> int:
    """
    Convert human strings like '24.83 Mb/s' or '488 Kb/s' to bps for sorting.
    """
    if bitrate is None:
        return 0
    if isinstance(bitrate, (int, float)):
        v = float(bitrate)
        if v > 1_000_000:
            return int(v)
        if v > 1_000:
            return int(v * 1000)
        return int(v)

    s = str(bitrate).strip()
    if not s or s.lower() == "null":
        return 0

    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMG])b/s\s*$", s, re.IGNORECASE)
    if not m:
        return 0

    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "K":
        return int(val * 1000)
    if unit == "M":
        return int(val * 1_000_000)
    if unit == "G":
        return int(val * 1_000_000_000)
    return 0


def _resolution_area(res: Any) -> int:
    if not res:
        return 0
    try:
        w, h = res
        return int(w) * int(h)
    except Exception:
        return 0


def _video_sort_key(t: Dict[str, Any]) -> Tuple[int, int]:
    # Mimic core/control.py sort: (area, bandwidth)
    area = _resolution_area(t.get("resolution"))
    bw = _safe_int(t.get("bandwidth"), 0)
    if not bw:
        bw = _parse_bitrate_to_bps(t.get("bitrate"))
    return (area, bw)


def _audio_sort_key(t: Dict[str, Any]) -> Tuple[int, int, str, str]:
    # Mimic core/control.py sort:
    # original first, AD last, then language, then channels
    return (
        0 if t.get("isOriginal") else 1,
        1 if t.get("isAD") else 0,
        str(t.get("language") or ""),
        str(t.get("channels") or ""),
    )


def _sub_sort_key(t: Dict[str, Any]) -> Tuple[str, int, int]:
    return (
        str(t.get("language") or ""),
        1 if t.get("isForced") else 0,
        1 if t.get("isSDH") else 0,
    )


def _with_ids(
    items: List[Dict[str, Any]],
    prefix: str,
    sort_key=None,
    reverse: bool = False
) -> List[Dict[str, Any]]:
    items2 = list(items)
    if sort_key:
        items2.sort(key=sort_key, reverse=reverse)
    out: List[Dict[str, Any]] = []
    for i, it in enumerate(items2):
        it2 = dict(it)
        it2["fid"] = f"{prefix}{i}"
        out.append(it2)
    return out


def index_tracks(hls: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Create deterministic v/a/s ids matching the same logic used by -F output.
    """
    vids = _with_ids(hls.get("video", []), "v", sort_key=_video_sort_key, reverse=True)
    auds = _with_ids(hls.get("audio", []), "a", sort_key=_audio_sort_key, reverse=False)
    subs = _with_ids(hls.get("subtitle", []), "s", sort_key=_sub_sort_key, reverse=False)
    return {"video": vids, "audio": auds, "subtitle": subs}


def _is_width_at_least(track: Dict[str, Any], wmin: int) -> bool:
    res = track.get("resolution")
    if not res:
        return False
    try:
        w, _h = res
        return int(w) >= int(wmin)
    except Exception:
        return False


def _select_best_video(
    tracks: List[Dict[str, Any]],
    *,
    want_range: str,
    min_width: int
) -> Optional[Dict[str, Any]]:
    cand = [
        t for t in tracks
        if str(t.get("range")) == want_range and _is_width_at_least(t, min_width)
    ]
    if not cand:
        return None
    cand.sort(key=_video_sort_key, reverse=True)
    return cand[0]


def _select_video_with_fallback(video_tracks: List[Dict[str, Any]], primary: Tuple[str, int]) -> Dict[str, Any]:
    """
    Fallback chain (as per requirements):
      - try primary (range,width)
      - fallback to 1080 SDR
      - fallback to ~720 SDR
      - hard error if nothing
    """
    primary_range, primary_wmin = primary

    v = _select_best_video(video_tracks, want_range=primary_range, min_width=primary_wmin)
    if v:
        return v

    v1080 = _select_best_video(video_tracks, want_range="SDR", min_width=1800)
    if v1080:
        return v1080

    v720 = _select_best_video(video_tracks, want_range="SDR", min_width=1200)
    if v720:
        return v720

    die("No suitable SDR video found (need at least ~720p SDR).")


def _audio_bps(t: Dict[str, Any]) -> int:
    return _parse_bitrate_to_bps(t.get("bitrate"))


def _best_audio_in_codec(
    audio_tracks: List[Dict[str, Any]],
    *,
    codec: str,
    lang: Optional[str],
    require_original: bool
) -> Optional[Dict[str, Any]]:
    cand = []
    for t in audio_tracks:
        if t.get("isAD"):
            continue
        if str(t.get("codec")) != codec:
            continue
        if require_original and not t.get("isOriginal"):
            continue
        if lang and str(t.get("language")) != lang:
            continue
        cand.append(t)

    if not cand:
        return None
    cand.sort(key=_audio_bps, reverse=True)
    return cand[0]


def _best_audio_aac_original(audio_tracks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Compatibility-first fallback:
      prefer AAC over HE-AAC, original language, highest bitrate.
    """
    a = _best_audio_in_codec(audio_tracks, codec="AAC", lang=None, require_original=True)
    if a:
        return a
    a = _best_audio_in_codec(audio_tracks, codec="HE-AAC", lang=None, require_original=True)
    if a:
        return a
    a = _best_audio_in_codec(audio_tracks, codec="AAC", lang=None, require_original=False)
    if a:
        return a
    return _best_audio_in_codec(audio_tracks, codec="HE-AAC", lang=None, require_original=False)


def _select_audio(
    audio_tracks: List[Dict[str, Any]],
    *,
    audio_quality: str,
    audio_lang: str,
    fixed_codec: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    audio_quality:
      - 'none' => return None
      - 'AAC'/'Atmos'/'DD5.1'
    audio_lang:
      - 'original' or BCP-47 code (e.g. en, cmn-Hans)
    fixed_codec:
      - if set, ignore audio_quality and force this codec (for preset_av profiles)
    """
    aq = (audio_quality or "").strip()
    al = (audio_lang or "").strip()

    if fixed_codec:
        aq = fixed_codec

    if aq.lower() == "none":
        return None

    if aq.lower() == "aac":
        want_codec = "AAC"
    elif aq.lower() == "atmos":
        want_codec = "Atmos"
    elif aq.lower() in ("dd5.1", "dd51", "dd5_1"):
        want_codec = "DD5.1"
    else:
        die(f"Unsupported audio_quality '{audio_quality}'")

    want_lang: Optional[str]
    require_original: bool
    if al.lower() == "original" or al == "":
        want_lang = None
        require_original = True
    else:
        want_lang = al
        require_original = False

    # 1) try requested codec
    if require_original:
        a = _best_audio_in_codec(audio_tracks, codec=want_codec, lang=None, require_original=True)
    else:
        a = _best_audio_in_codec(audio_tracks, codec=want_codec, lang=want_lang, require_original=False)

    if a:
        return a

    # 2) fallback to best original AAC (compat)
    return _best_audio_aac_original(audio_tracks)


def _select_subtitle(sub_tracks: List[Dict[str, Any]], sub_lang: str) -> Optional[Dict[str, Any]]:
    sl = (sub_lang or "").strip()
    if sl.lower() in ("", "none", "off", "no"):
        return None

    cand = [t for t in sub_tracks if str(t.get("language")) == sl]
    if not cand:
        return None

    # prefer Normal: not SDH, not forced
    def pref_key(t: Dict[str, Any]) -> Tuple[int, int]:
        return (1 if t.get("isSDH") else 0, 1 if t.get("isForced") else 0)

    cand.sort(key=pref_key)
    return cand[0]


@dataclass
class PresetAVProfile:
    name: str
    want_video_range: str
    want_video_min_width: int
    fixed_audio_codec: str  # AAC / Atmos / DD5.1


@dataclass
class PresetVideoProfile:
    name: str
    primary_video_range: str
    primary_video_min_width: int


PRESET_AV_PROFILES: Dict[str, PresetAVProfile] = {
    "1080_SDR_AAC": PresetAVProfile(
        name="1080p SDR + AAC (best bitrate, original)",
        want_video_range="SDR",
        want_video_min_width=1800,
        fixed_audio_codec="AAC",
    ),
    "4K_DOVI_ATMOS": PresetAVProfile(
        name="4K DoVi + Atmos (best bitrate, original)",
        want_video_range="DoVi",
        want_video_min_width=3500,
        fixed_audio_codec="Atmos",
    ),
    "4K_HDR_DD51": PresetAVProfile(
        name="4K HDR + DD5.1 (best bitrate, original)",
        want_video_range="HDR",
        want_video_min_width=3500,
        fixed_audio_codec="DD5.1",
    ),
}

PRESET_VIDEO_PROFILES: Dict[str, PresetVideoProfile] = {
    "1080_SDR": PresetVideoProfile(
        name="1080p SDR (best bitrate)",
        primary_video_range="SDR",
        primary_video_min_width=1800,
    ),
    "4K_DOVI": PresetVideoProfile(
        name="4K DoVi (best bitrate)",
        primary_video_range="DoVi",
        primary_video_min_width=3500,
    ),
    "4K_HDR": PresetVideoProfile(
        name="4K HDR (best bitrate)",
        primary_video_range="HDR",
        primary_video_min_width=3500,
    ),
}


def _format_expr(v: Dict[str, Any], a: Optional[Dict[str, Any]], s: Optional[Dict[str, Any]]) -> str:
    parts = [v["fid"]]
    if a:
        parts.append(a["fid"])
    if s:
        parts.append(s["fid"])
    return "+".join(parts)


def _fetch_trailer_item(url: str, *, trailer_idx: int, default_only: bool) -> Dict[str, Any]:
    atvp = AppleTVPlus()
    trailers = atvp.get_info(url, default_only)
    if not trailers:
        die("No trailers found for URL.")
    if trailer_idx < 0 or trailer_idx >= len(trailers):
        die(f"Trailer index t{trailer_idx} out of range (0..{len(trailers)-1}).")
    return trailers[trailer_idx]


def _select_effective_format_custom(expr: str) -> str:
    """
    For mode=custom. Lightweight sanity check.
    Must include exactly one vN. Empty means "list-only" in workflow.
    """
    if not expr or not expr.strip():
        return ""

    tokens = [t.strip() for t in expr.split("+") if t.strip()]
    v = [t for t in tokens if re.match(r"^[vV][0-9]+$", t)]
    if len(v) != 1:
        die("Custom format must include exactly one video token vN (e.g. v6+a0+s4).")
    for t in tokens:
        if not re.match(r"^[vVaAsS][0-9]+$", t):
            die(f"Invalid token in custom format: '{t}' (expected vN/aN/sN).")
    tokens = [t.lower() for t in tokens]
    return "+".join(tokens)


def _select_preset_av(
    indexed: Dict[str, List[Dict[str, Any]]],
    *,
    profile_key: str,
    audio_lang: str,
    sub_lang: str,
) -> str:
    prof = PRESET_AV_PROFILES.get(profile_key)
    if not prof:
        die(f"Unknown preset_av_profile '{profile_key}'")

    vids = indexed["video"]
    auds = indexed["audio"]
    subs = indexed["subtitle"]

    v = _select_video_with_fallback(vids, (prof.want_video_range, prof.want_video_min_width))

    a = _select_audio(auds, audio_quality="ignored", audio_lang=audio_lang, fixed_codec=prof.fixed_audio_codec)
    if a is None:
        eprint("[selector] WARN: audio not selected (no suitable audio found); output will be video-only.")

    s = _select_subtitle(subs, sub_lang)

    eprint(f"[selector] preset_av_profile={profile_key} -> {prof.name}")
    eprint(f"[selector] selected video: {v['fid']} range={v.get('range')} res={v.get('resolution')} br={v.get('bitrate')}")
    if a:
        eprint(f"[selector] selected audio: {a['fid']} codec={a.get('codec')} lang={a.get('language')} br={a.get('bitrate')} OG={a.get('isOriginal')}")
    else:
        eprint("[selector] selected audio: (none)")
    if s:
        eprint(f"[selector] selected subtitle: {s['fid']} lang={s.get('language')} forced={s.get('isForced')} sdh={s.get('isSDH')}")
    else:
        eprint("[selector] selected subtitle: (none)")

    return _format_expr(v, a, s)


def _select_preset_video(
    indexed: Dict[str, List[Dict[str, Any]]],
    *,
    profile_key: str,
    audio_quality: str,
    audio_lang: str,
    sub_lang: str,
) -> str:
    prof = PRESET_VIDEO_PROFILES.get(profile_key)
    if not prof:
        die(f"Unknown preset_video_profile '{profile_key}'")

    vids = indexed["video"]
    auds = indexed["audio"]
    subs = indexed["subtitle"]

    v = _select_video_with_fallback(vids, (prof.primary_video_range, prof.primary_video_min_width))

    a = _select_audio(auds, audio_quality=audio_quality, audio_lang=audio_lang, fixed_codec=None)
    s = _select_subtitle(subs, sub_lang)

    eprint(f"[selector] preset_video_profile={profile_key} -> {prof.name}")
    eprint(f"[selector] selected video: {v['fid']} range={v.get('range')} res={v.get('resolution')} br={v.get('bitrate')}")

    if (audio_quality or "").strip().lower() == "none":
        eprint("[selector] audio_quality=none -> selected audio: (none)")
    else:
        if a:
            eprint(f"[selector] selected audio: {a['fid']} codec={a.get('codec')} lang={a.get('language')} br={a.get('bitrate')} OG={a.get('isOriginal')}")
        else:
            eprint("[selector] WARN: audio not selected (no suitable audio found); output will be video-only.")

    if s:
        eprint(f"[selector] selected subtitle: {s['fid']} lang={s.get('language')} forced={s.get('isForced')} sdh={s.get('isSDH')}")
    else:
        eprint("[selector] selected subtitle: (none)")

    return _format_expr(v, a, s)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Select Manzana -f format string for preset/custom workflow modes."
    )

    p.add_argument("--url", required=True, help="Apple TV page URL")
    p.add_argument("--trailer", default="t0", help='Trailer selector (t0, t1, ...). "all" is not supported in presets v0.1.x')
    p.add_argument("--default-only", action="store_true", help="Use Manzana --default logic (default background video)")
    p.add_argument("--mode", required=True, choices=["preset_av", "preset_video", "custom"], help="Selection mode")

    # preset_av
    p.add_argument("--preset-av-profile", default="1080_SDR_AAC", help="Preset AV profile key")
    # preset_video
    p.add_argument("--preset-video-profile", default="1080_SDR", help="Preset video profile key")
    p.add_argument("--audio-quality", default="AAC", help="AAC/Atmos/DD5.1/none (only used in preset_video)")
    # preset_* optional
    p.add_argument("--audio-lang", default="original", help='Audio language: "original" or language code (e.g. en, cmn-Hans)')
    p.add_argument("--sub-lang", default="none", help='Subtitle language code or "none"')

    # custom
    p.add_argument("--custom-format", default="", help='Custom -f expression, e.g. "v6+a0+s4"')

    args = p.parse_args(argv)

    trailer_idx = _parse_trailer_arg(args.trailer)

    # custom mode: we don't need to fetch tracks if format is empty (meaning list-only)
    if args.mode == "custom":
        eff = _select_effective_format_custom(args.custom_format)
        print(eff)
        return 0

    item = _fetch_trailer_item(args.url, trailer_idx=trailer_idx, default_only=bool(args.default_only))
    master_url = item.get("hlsUrl")
    if not master_url:
        die("No hlsUrl found in selected trailer item.")

    hls = get_hls(master_url)
    indexed = index_tracks(hls)

    if not indexed["video"]:
        die("No video tracks found.")

    if args.mode == "preset_av":
        eff = _select_preset_av(
            indexed,
            profile_key=str(args.preset_av_profile),
            audio_lang=str(args.audio_lang),
            sub_lang=str(args.sub_lang),
        )
    elif args.mode == "preset_video":
        eff = _select_preset_video(
            indexed,
            profile_key=str(args.preset_video_profile),
            audio_quality=str(args.audio_quality),
            audio_lang=str(args.audio_lang),
            sub_lang=str(args.sub_lang),
        )
    else:
        die(f"Unknown mode '{args.mode}'")

    print(eff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
