#!/usr/bin/env python3
# tools/select_format.py @ v0.1.3
#
# Fix in v0.1.3 (Best scheme agreed):
#   Define resolution "bands" to make 1080 presets truly pick the FHD-width ladder
#   and avoid picking mid/3K variants like 2966x1240.
#
#   Bands (by width):
#     - UHD (4K-width):        width >= 3500
#     - FHD (our "1080"):      1700 <= width < 2200   (covers 1918/1920 and allows 2048)
#     - HD (our "720-like"):   1100 <= width < 1700   (covers 1482, 1186, etc.)
#     - SD (last resort):       700 <= width < 1100   (covers 862, 890, etc.)
#
#   Preset behavior:
#     - preset_video_profile=1080_SDR:
#         pick best SDR in FHD band; if none -> best SDR in HD band; if none -> best SDR in SD band; else error.
#     - preset_video_profile=4K_DOVI / 4K_HDR:
#         pick best DoVi/HDR in UHD band; if none -> fallback chain to SDR FHD -> SDR HD -> SDR SD -> error.
#     - preset_av_profile=1080_SDR_AAC:
#         same video band logic as 1080_SDR (FHD SDR), with same fallback chain.
#
# Keeps v0.1.1 fix:
#   Redirect Manzana Rich Console logs to stderr so selector stdout stays clean.
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

        manzana_logger.cons = Console(file=sys.stderr)
    except Exception:
        pass


_redirect_manzana_logs_to_stderr()


try:
    from core.api.aptv import AppleTVPlus
    from core.api.hls import get_hls
except Exception as e:
    raise RuntimeError(
        "Unable to import Manzana modules. Run this script from repository root, "
        "or ensure repo is on PYTHONPATH."
    ) from e


# --- Resolution bands (by width) ---
WIDTH_UHD_MIN = 3500

WIDTH_FHD_MIN = 1700
WIDTH_FHD_MAX_EXCL = 2200

WIDTH_HD_MIN = 1100
WIDTH_HD_MAX_EXCL = 1700

WIDTH_SD_MIN = 700
WIDTH_SD_MAX_EXCL = 1100


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
    vids = _with_ids(hls.get("video", []), "v", sort_key=_video_sort_key, reverse=True)
    auds = _with_ids(hls.get("audio", []), "a", sort_key=_audio_sort_key, reverse=False)
    subs = _with_ids(hls.get("subtitle", []), "s", sort_key=_sub_sort_key, reverse=False)
    return {"video": vids, "audio": auds, "subtitle": subs}


def _track_width(track: Dict[str, Any]) -> int:
    res = track.get("resolution")
    if not res:
        return 0
    try:
        w, _h = res
        return int(w)
    except Exception:
        return 0


def _in_width_band(track: Dict[str, Any], min_width: int, max_width_exclusive: Optional[int]) -> bool:
    w = _track_width(track)
    if w < min_width:
        return False
    if max_width_exclusive is not None and w >= max_width_exclusive:
        return False
    return True


def _select_best_video(
    tracks: List[Dict[str, Any]],
    *,
    want_range: str,
    min_width: int,
    max_width_exclusive: Optional[int]
) -> Optional[Dict[str, Any]]:
    cand = [
        t for t in tracks
        if str(t.get("range")) == want_range and _in_width_band(t, min_width, max_width_exclusive)
    ]
    if not cand:
        return None
    cand.sort(key=_video_sort_key, reverse=True)
    return cand[0]


def _select_video_with_band_fallback(
    video_tracks: List[Dict[str, Any]],
    primary: Tuple[str, int, Optional[int]],
) -> Dict[str, Any]:
    """
    Fallback chain:
      - try primary
      - fallback to SDR in FHD band (1700-2200)
      - fallback to SDR in HD band  (1100-1700)
      - fallback to SDR in SD band  (700-1100)
      - hard error if nothing
    """
    primary_range, primary_minw, primary_maxw = primary

    v = _select_best_video(
        video_tracks,
        want_range=primary_range,
        min_width=primary_minw,
        max_width_exclusive=primary_maxw,
    )
    if v:
        return v

    v_fhd = _select_best_video(
        video_tracks,
        want_range="SDR",
        min_width=WIDTH_FHD_MIN,
        max_width_exclusive=WIDTH_FHD_MAX_EXCL,
    )
    if v_fhd:
        return v_fhd

    v_hd = _select_best_video(
        video_tracks,
        want_range="SDR",
        min_width=WIDTH_HD_MIN,
        max_width_exclusive=WIDTH_HD_MAX_EXCL,
    )
    if v_hd:
        return v_hd

    v_sd = _select_best_video(
        video_tracks,
        want_range="SDR",
        min_width=WIDTH_SD_MIN,
        max_width_exclusive=WIDTH_SD_MAX_EXCL,
    )
    if v_sd:
        return v_sd

    die("No suitable SDR video found (need at least an SD ladder).")


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

    if require_original:
        a = _best_audio_in_codec(audio_tracks, codec=want_codec, lang=None, require_original=True)
    else:
        a = _best_audio_in_codec(audio_tracks, codec=want_codec, lang=want_lang, require_original=False)

    if a:
        return a

    return _best_audio_aac_original(audio_tracks)


def _select_subtitle(sub_tracks: List[Dict[str, Any]], sub_lang: str) -> Optional[Dict[str, Any]]:
    sl = (sub_lang or "").strip()
    if sl.lower() in ("", "none", "off", "no"):
        return None

    cand = [t for t in sub_tracks if str(t.get("language")) == sl]
    if not cand:
        return None

    def pref_key(t: Dict[str, Any]) -> Tuple[int, int]:
        return (1 if t.get("isSDH") else 0, 1 if t.get("isForced") else 0)

    cand.sort(key=pref_key)
    return cand[0]


@dataclass
class PresetAVProfile:
    name: str
    want_video_range: str
    want_video_min_width: int
    want_video_max_width_exclusive: Optional[int]
    fixed_audio_codec: str  # AAC / Atmos / DD5.1


@dataclass
class PresetVideoProfile:
    name: str
    primary_video_range: str
    primary_video_min_width: int
    primary_video_max_width_exclusive: Optional[int]


# Preset AV profiles:
# - 1080_SDR_AAC uses STRICT FHD band (1700-2200)
# - 4K profiles target width >= 3500 (no upper bound)
PRESET_AV_PROFILES: Dict[str, PresetAVProfile] = {
    "1080_SDR_AAC": PresetAVProfile(
        name="1080 (FHD-width) SDR + AAC (best bitrate, original) [BAND: 1700-2200]",
        want_video_range="SDR",
        want_video_min_width=WIDTH_FHD_MIN,
        want_video_max_width_exclusive=WIDTH_FHD_MAX_EXCL,
        fixed_audio_codec="AAC",
    ),
    "4K_DOVI_ATMOS": PresetAVProfile(
        name="4K DoVi + Atmos (best bitrate, original)",
        want_video_range="DoVi",
        want_video_min_width=WIDTH_UHD_MIN,
        want_video_max_width_exclusive=None,
        fixed_audio_codec="Atmos",
    ),
    "4K_HDR_DD51": PresetAVProfile(
        name="4K HDR + DD5.1 (best bitrate, original)",
        want_video_range="HDR",
        want_video_min_width=WIDTH_UHD_MIN,
        want_video_max_width_exclusive=None,
        fixed_audio_codec="DD5.1",
    ),
}

# Preset video profiles:
# - 1080_SDR uses STRICT FHD band (1700-2200)
PRESET_VIDEO_PROFILES: Dict[str, PresetVideoProfile] = {
    "1080_SDR": PresetVideoProfile(
        name="1080 (FHD-width) SDR (best bitrate) [BAND: 1700-2200]",
        primary_video_range="SDR",
        primary_video_min_width=WIDTH_FHD_MIN,
        primary_video_max_width_exclusive=WIDTH_FHD_MAX_EXCL,
    ),
    "4K_DOVI": PresetVideoProfile(
        name="4K DoVi (best bitrate)",
        primary_video_range="DoVi",
        primary_video_min_width=WIDTH_UHD_MIN,
        primary_video_max_width_exclusive=None,
    ),
    "4K_HDR": PresetVideoProfile(
        name="4K HDR (best bitrate)",
        primary_video_range="HDR",
        primary_video_min_width=WIDTH_UHD_MIN,
        primary_video_max_width_exclusive=None,
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

    v = _select_video_with_band_fallback(
        vids,
        (prof.want_video_range, prof.want_video_min_width, prof.want_video_max_width_exclusive),
    )

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

    v = _select_video_with_band_fallback(
        vids,
        (prof.primary_video_range, prof.primary_video_min_width, prof.primary_video_max_width_exclusive),
    )

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
    p = argparse.ArgumentParser(description="Select Manzana -f format string for preset/custom workflow modes.")

    p.add_argument("--url", required=True, help="Apple TV page URL")
    p.add_argument("--trailer", default="t0", help='Trailer selector (t0, t1, ...). "all" is not supported in presets v0.1.x')
    p.add_argument("--default-only", action="store_true", help="Use Manzana --default logic (default background video)")
    p.add_argument("--mode", required=True, choices=["preset_av", "preset_video", "custom"], help="Selection mode")

    p.add_argument("--preset-av-profile", default="1080_SDR_AAC", help="Preset AV profile key")
    p.add_argument("--preset-video-profile", default="1080_SDR", help="Preset video profile key")
    p.add_argument("--audio-quality", default="AAC", help="AAC/Atmos/DD5.1/none (only used in preset_video)")
    p.add_argument("--audio-lang", default="original", help='Audio language: "original" or language code (e.g. en, cmn-Hans)')
    p.add_argument("--sub-lang", default="none", help='Subtitle language code or "none"')

    p.add_argument("--custom-format", default="", help='Custom -f expression, e.g. "v6+a0+s4"')

    args = p.parse_args(argv)

    trailer_idx = _parse_trailer_arg(args.trailer)

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
