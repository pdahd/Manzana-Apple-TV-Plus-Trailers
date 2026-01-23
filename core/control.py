import os
import sys
import shutil
import re
import unicodedata
from rich.console import Console
from rich import box
from rich.table import Table
from rich.columns import Columns

from core.api import AppleTVPlus
from core.api import get_hls

# legacy interactive selectors
from core.user import get_select
from core.user import user_video
from core.user import user_audio
from core.user import user_subs

from core.parse import parse_uri
from core.process import download
from core.process import appendFiles
from core.tagger import tagFile

from utils import logger, sanitize
from utils.bootstrap_tools import ensure_mp4box, ensure_ffmpeg

# core/control.py @ v2.4.3
# Changes vs v2.4.2:
# - Add runtime bootstrap for FFmpeg (BtbN bundle mirror):
#   - Only when subtitle tracks are selected (sN present)
#   - If system ffmpeg meets minimal version, use it
#   - Otherwise auto-download/use our bundled ffmpeg (ffmpeg-bundle-latest)
# - Keep all existing interactive/non-interactive logic unchanged.
#
# Keeps v2.4.1 policy:
# - Fix "prefix dedup" misses caused by punctuation/fullwidth variants:
#   Compare and cut prefix using NFKC-normalized strings + whitespace collapse.
# - If the remaining suffix starts with parentheses/brackets, join with space instead of " - "
#   so we get: "Movie (字幕吹替) (2014) Apple-Trailer.mp4" rather than "Movie - (字幕吹替)..."
# - Keep v2.4.0 policy:
#   "{MovieTitle} - {VideoTitle (dedup)} ({Year}) Apple-Trailer.mp4"
#   Apple-Trailer always immediately before ".mp4"
#   Auto (2)/(3)... on name collision
#   No [WEB-DL]/[ATVP]/[t0]/[clip-...] in final delivery name


cons = Console()


def __get_path():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


TEMPDIR = os.path.join(__get_path(), "temp")
OUTPUTDIR = os.path.join(__get_path(), "output")

if not os.path.exists(TEMPDIR):
    os.makedirs(TEMPDIR)

if not os.path.exists(OUTPUTDIR):
    os.makedirs(OUTPUTDIR)


def _print_trailers(trailers: list):
    table = Table(box=box.ROUNDED)
    table.add_column("ID", justify="center")
    table.add_column("Content", justify="left")
    table.add_column("Name", justify="left")

    for i, t in enumerate(trailers):
        table.add_row(f"t{i}", t.get("title", ""), t.get("videoTitle", ""))

    print()
    cons.print(Columns(["       ", table]))
    print()


def _select_trailers(trailers: list, trailer_arg: str, no_prompt: bool):
    if trailer_arg is None:
        if (not no_prompt) and sys.stdin.isatty():
            return get_select(trailers)
        logger.error('No trailer selected. Use "--list-trailers" then "--trailer t0".', 1)

    ta = trailer_arg.strip().lower()
    if ta in ("all", "a"):
        return trailers

    if ta.startswith("t"):
        ta = ta[1:]

    if not ta.isdigit():
        logger.error('Invalid --trailer value. Use t0/t1/... or "all".', 1)

    idx = int(ta)
    if idx < 0 or idx >= len(trailers):
        logger.error("Trailer index out of range.", 1)

    return [trailers[idx]]


def _video_sort_key(t: dict):
    res = t.get("resolution") or (0, 0)
    try:
        w, h = res
        area = int(w) * int(h)
    except Exception:
        area = 0
    bw = t.get("bandwidth") or 0
    return (area, int(bw))


def _audio_sort_key(t: dict):
    return (
        0 if t.get("isOriginal") else 1,
        1 if t.get("isAD") else 0,
        (t.get("language") or ""),
        (t.get("channels") or ""),
    )


def _sub_sort_key(t: dict):
    return (
        (t.get("language") or ""),
        1 if t.get("isForced") else 0,
        1 if t.get("isSDH") else 0,
    )


def _with_ids(items: list, prefix: str, sort_key=None, reverse=False):
    items2 = list(items)
    if sort_key:
        items2.sort(key=sort_key, reverse=reverse)

    out = []
    for i, it in enumerate(items2):
        it2 = dict(it)
        it2["fid"] = f"{prefix}{i}"
        out.append(it2)
    return out


def _index_tracks(hls: dict):
    vids = _with_ids(hls.get("video", []), "v", sort_key=_video_sort_key, reverse=True)
    auds = _with_ids(hls.get("audio", []), "a", sort_key=_audio_sort_key, reverse=False)
    subs = _with_ids(hls.get("subtitle", []), "s", sort_key=_sub_sort_key, reverse=False)
    return {"video": vids, "audio": auds, "subtitle": subs}


def _print_formats(item_meta: dict, master_url: str, indexed: dict, page_url: str, trailer_hint: str):
    print()
    cons.print(f'\tContent: [i bold purple]{item_meta.get("videoTitle","")}[/]')
    cons.print(f"\tMaster M3U8: [bold]{master_url}[/]")
    print()

    vtable = Table(box=box.ROUNDED)
    vtable.add_column("ID", justify="center")
    vtable.add_column("Codec", justify="left")
    vtable.add_column("Bitrate", justify="left")
    vtable.add_column("Resolution", justify="left")
    vtable.add_column("FPS", justify="center")
    vtable.add_column("Range", justify="left")

    for v in indexed["video"]:
        res = v.get("resolution")
        res_str = f"{res[0]}x{res[1]}" if res else "Null"
        vtable.add_row(
            v["fid"],
            str(v.get("codec")),
            str(v.get("bitrate")),
            res_str,
            str(v.get("fps")),
            str(v.get("range")),
        )

    atable = Table(box=box.ROUNDED)
    atable.add_column("ID", justify="center")
    atable.add_column("Codec", justify="left")
    atable.add_column("Bitrate", justify="center")
    atable.add_column("Channels", justify="center")
    atable.add_column("Language", justify="center")
    atable.add_column("OG", justify="left")
    atable.add_column("AD", justify="left")

    for a in indexed["audio"]:
        atable.add_row(
            a["fid"],
            str(a.get("codec")),
            str(a.get("bitrate")),
            str(a.get("channels")),
            str(a.get("language")),
            "YES" if a.get("isOriginal") else "NO",
            "YES" if a.get("isAD") else "NO",
        )

    stable = Table(box=box.ROUNDED)
    stable.add_column("ID", justify="center")
    stable.add_column("Language", justify="center")
    stable.add_column("Forced", justify="center")
    stable.add_column("SDH", justify="center")
    stable.add_column("Name", justify="left")

    for s in indexed["subtitle"]:
        stable.add_row(
            s["fid"],
            str(s.get("language")),
            "YES" if s.get("isForced") else "NO",
            "YES" if s.get("isSDH") else "NO",
            str(s.get("name")),
        )

    cons.print(Columns(["       ", vtable]))
    print()
    cons.print(Columns(["       ", atable]))
    print()
    cons.print(Columns(["       ", stable]))
    print()

    cons.print("[bold]Example download command:[/]")
    cons.print(f'  python manzana.py --no-prompt --trailer {trailer_hint} -f "v0+a0" "{page_url}"')
    print()


def _parse_format_expr(expr: str):
    tokens = [t.strip() for t in expr.split("+") if t.strip()]
    v = []
    a = []
    s = []

    for t in tokens:
        tl = t.lower()
        if (len(tl) >= 2) and (tl[0] in ("v", "a", "s")) and tl[1:].isdigit():
            if tl[0] == "v":
                v.append(tl)
            elif tl[0] == "a":
                a.append(tl)
            elif tl[0] == "s":
                s.append(tl)
        else:
            logger.error(f'Invalid token in -f/--format: "{t}" (expected v0/a0/s0)', 1)

    if len(v) == 0:
        logger.error('No video selected. Use -F to list formats, then -f like "v0+a0".', 1)
    if len(v) > 1:
        logger.error("Only one video stream is supported in output (select one vID).", 1)

    return v[0], a, s


def _select_by_format(expr: str, indexed: dict):
    v_id, a_ids, s_ids = _parse_format_expr(expr)

    vmap = {x["fid"]: x for x in indexed["video"]}
    amap = {x["fid"]: x for x in indexed["audio"]}
    smap = {x["fid"]: x for x in indexed["subtitle"]}

    if v_id not in vmap:
        logger.error(f'Video id "{v_id}" not found. Use -F to list.', 1)

    selected = [vmap[v_id]]

    for aid in a_ids:
        if aid not in amap:
            logger.error(f'Audio id "{aid}" not found. Use -F to list.', 1)
        selected.append(amap[aid])

    for sid in s_ids:
        if sid not in smap:
            logger.error(f'Subtitle id "{sid}" not found. Use -F to list.', 1)
        selected.append(smap[sid])

    return selected


def _ensure_tools(selected_tracks: list):
    # Ensure MP4Box exists (auto-download bundle if missing/too old)
    ensure_mp4box(min_gpac_version=(2, 0))
    if not shutil.which("MP4Box"):
        logger.error('Unable to find "MP4Box" in PATH! (required for muxing)', 1)

    # Ensure ffmpeg ONLY when subtitles are requested
    need_ffmpeg = any(t.get("type") == "subtitle" for t in selected_tracks)
    if need_ffmpeg:
        ensure_ffmpeg(min_ffmpeg_version=(4, 2))
        if not shutil.which("ffmpeg"):
            logger.error('Unable to find "ffmpeg" in PATH! (required for subtitle conversion)', 1)


def _norm_for_prefix_compare(s: str) -> str:
    """
    Normalize string for prefix comparison:
    - NFKC to unify fullwidth/halfwidth punctuation (&/＆, ：/:, etc.)
    - collapse whitespace
    """
    s = unicodedata.normalize("NFKC", str(s or "")).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _dedup_video_title_prefix(movie_title: str, video_title: str) -> str:
    """
    Remove repeated movie title prefix from video title, using NFKC-normalized comparison.

    Example:
      movie_title="X-MEN：フューチャー&パスト"
      video_title="X-MEN：フューチャー＆パスト (字幕/吹替)"
    => returns "(字幕/吹替)"
    """
    mt_raw = str(movie_title or "").strip()
    vt_raw = str(video_title or "").strip()
    if not mt_raw or not vt_raw:
        return vt_raw

    mt = _norm_for_prefix_compare(mt_raw)
    vt = _norm_for_prefix_compare(vt_raw)

    if not mt or not vt:
        return vt_raw

    if vt.startswith(mt):
        rest = vt[len(mt):].strip()
        # strip common separators after prefix
        rest = rest.lstrip(" -–—:：|・･")
        rest = rest.strip()
        return rest

    return vt_raw


def _build_delivery_basename(movie_title: str, video_title: str, year: str) -> str:
    """
    Build user-facing base name WITHOUT extension.
    Must end with " Apple-Trailer" (immediately before .mp4).
    """

    # year normalize
    y = (year or "").strip()
    if not y or not re.match(r"^\d{4}$", y):
        y = "0000"

    mt_raw = str(movie_title or "").strip()
    vt_raw = str(video_title or "").strip()

    # Dedup: get a "rest" (may be "(字幕/吹替)" or "ローグ・エディション (字幕/吹替)")
    rest = _dedup_video_title_prefix(mt_raw, vt_raw)
    rest = str(rest or "").strip()

    # Decide join style:
    # - If rest is empty: just movie title
    # - If rest starts with brackets: join with space (more natural)
    # - Else: join with " - "
    mt_disp = mt_raw
    if not mt_disp:
        mt_disp = "manzana_output"

    if not rest or _norm_for_prefix_compare(rest) == _norm_for_prefix_compare(mt_disp):
        core = f"{mt_disp} ({y})"
    else:
        if rest[:1] in ("(", "（", "[", "【"):
            core = f"{mt_disp} {rest} ({y})"
        else:
            core = f"{mt_disp} - {rest} ({y})"

    core = sanitize(core)
    if not core:
        core = "manzana_output (0000)"

    base = f"{core} Apple-Trailer"
    base = sanitize(base)
    if not base:
        base = "manzana_output (0000) Apple-Trailer"

    return base


def _unique_output_path(base_no_ext: str, out_dir: str) -> str:
    """
    Ensure output filename uniqueness by appending (2), (3)... BEFORE 'Apple-Trailer'.
    Keep 'Apple-Trailer' immediately before .mp4.
    """
    base_no_ext = sanitize(base_no_ext)
    if not base_no_ext:
        base_no_ext = "manzana_output (0000) Apple-Trailer"

    suffix = " Apple-Trailer"
    if base_no_ext.endswith(suffix):
        stem_core = base_no_ext[: -len(suffix)].rstrip()
    else:
        stem_core = base_no_ext

    def make(n: int) -> str:
        if n <= 1:
            bn = f"{stem_core}{suffix}"
        else:
            bn = f"{stem_core} ({n}){suffix}"
        bn = sanitize(bn)
        if not bn:
            bn = f"manzana_output (0000) ({n}){suffix}"
        return os.path.join(out_dir, bn + ".mp4")

    p = make(1)
    if not os.path.exists(p):
        return p

    for i in range(2, 1000):
        p2 = make(i)
        if not os.path.exists(p2):
            return p2

    logger.error("Unable to find a free output filename (too many duplicates).", 1)
    return make(9999)


def run(args):
    try:
        atvp = AppleTVPlus()
        trailers = atvp.get_info(args.url, args.default)

        if args.listTrailers:
            logger.info("Listing trailers...")
            _print_trailers(trailers)
            return

        selected_trailers = _select_trailers(trailers, args.trailer, args.noPrompt)

        for ti, item in enumerate(selected_trailers):
            master_url = item["hlsUrl"]

            if args.listFormats:
                logger.info(f'Listing formats for {item.get("title","")} | {item.get("videoTitle","")}')
                hls = get_hls(master_url)
                indexed = _index_tracks(hls)
                trailer_hint = args.trailer if args.trailer else f"t{ti}"
                _print_formats(item, master_url, indexed, args.url, trailer_hint)
                print("-" * 30)
                continue

            year = str(item.get("releaseDate") or "")[0:4] or "0000"
            base = _build_delivery_basename(
                movie_title=str(item.get("title") or ""),
                video_title=str(item.get("videoTitle") or ""),
                year=year,
            )
            op = _unique_output_path(base, OUTPUTDIR)

            logger.info(f'Preparing {item.get("title","")} | {item.get("videoTitle","")}')
            logger.info(f"Output file: {os.path.basename(op)}")

            hls = get_hls(master_url)
            indexed = _index_tracks(hls)

            if args.format:
                if args.noAudio or args.noSubs:
                    logger.warning('"-f/--format" provided; ignoring --no-audio/--no-subs')
                userReq = _select_by_format(args.format, indexed)
            else:
                if args.noPrompt or (not sys.stdin.isatty()):
                    logger.error('Non-interactive mode: please use -F to list formats and -f to select.', 1)

                print()
                cons.print(f'\tContent: [i bold purple]{item["videoTitle"]}[/]')
                print()

                userVideo = user_video(hls["video"])
                if not args.noAudio:
                    userAudio = user_audio(hls["audio"])
                else:
                    userAudio = []
                if not args.noSubs:
                    userSubs = user_subs(hls["subtitle"])
                else:
                    userSubs = []

                userReq = userVideo + userAudio + userSubs

            logger.info("Fetching m3u8...")

            try:
                parse_uri(userReq)
            except Exception:
                parse_uri(userReq, ssl=False)

            logger.info("Downloading segments...")

            _ensure_tools(userReq)

            print()
            try:
                download(userReq)
            except Exception:
                download(userReq, ssl=False)
            print()

            logger.info("Appending segments...")
            appendFiles(userReq)

            logger.info("Saving output...")
            shutil.move(os.path.join(TEMPDIR, "output.mp4"), op)

            logger.info("Tagging...")
            tagFile(item, op)

            print("-" * 30)

        logger.info("Cleaning temp...")
        if os.path.exists(TEMPDIR):
            for temp in os.listdir(TEMPDIR):
                try:
                    os.remove(os.path.join(TEMPDIR, temp))
                except PermissionError:
                    logger.error(f"Unable to remove '{temp}' temp! Remove it manually...")

            try:
                os.removedirs(TEMPDIR)
            except OSError:
                pass

        logger.info("Done.")
    except KeyboardInterrupt:
        print()
        logger.error("Interrupted by user.")
