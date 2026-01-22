import os
import sys
import shutil
from rich.console import Console
from rich import box
from rich.table import Table
from rich.columns import Columns
from urllib.parse import urlparse

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

# core/control.py @ v2.3.3
# Changes vs v2.3.2:
# - Filename safety (artifact/windows-safe) double-guard:
#     After assembling the full base filename (including [tN] and [clip-...]),
#     sanitize the WHOLE base_name again to ensure no ":" etc can appear due to
#     normalization effects or unexpected characters.
# - Keep v2.3.2 human-readable logs (Preparing..., Output file: ...).
# - Keep v2.3.1 collision avoidance: [tN] suffix + [clip-<id>] suffix for clip URLs.


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


def _normalize_trailer_tag(trailer_arg: str, fallback: str) -> str:
    if not trailer_arg:
        return fallback
    ta = trailer_arg.strip().lower()
    if ta in ("all", "a"):
        return fallback
    if ta.startswith("t"):
        ta = ta[1:]
    if ta.isdigit():
        return f"t{int(ta)}"
    return fallback


def _clip_id_suffix_from_url(page_url: str):
    try:
        u = urlparse(page_url)
        parts = [p for p in u.path.split("/") if p]
        # parts: [storefront, kind, slug, id]
        if len(parts) >= 4 and parts[1] == "clip":
            last = parts[-1]
            if last.startswith("umc.cmc."):
                return last.split("umc.cmc.", 1)[1]
            return last
    except Exception:
        pass
    return None


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
    if not shutil.which("MP4Box"):
        logger.error('Unable to find "MP4Box" in PATH! (required for muxing)', 1)

    need_ffmpeg = any(t.get("type") == "subtitle" for t in selected_tracks)
    if need_ffmpeg and (not shutil.which("ffmpeg")):
        logger.error('Unable to find "ffmpeg" in PATH! (required for subtitle conversion)', 1)


def run(args):
    try:
        atvp = AppleTVPlus()
        trailers = atvp.get_info(args.url, args.default)

        if args.listTrailers:
            logger.info("Listing trailers...")
            _print_trailers(trailers)
            return

        selected_trailers = _select_trailers(trailers, args.trailer, args.noPrompt)

        # For clip URLs, append a clip id suffix to filename (avoids collisions across multiple clips)
        clip_suffix = _clip_id_suffix_from_url(args.url)

        for ti, item in enumerate(selected_trailers):
            trailer_tag = _normalize_trailer_tag(args.trailer, fallback=f"t{ti}")
            trailer_hint = trailer_tag

            master_url = item["hlsUrl"]

            # list formats mode
            if args.listFormats:
                logger.info(f'Listing formats for [{trailer_tag}] {item.get("title","")} | {item.get("videoTitle","")}')
                hls = get_hls(master_url)
                indexed = _index_tracks(hls)
                _print_formats(item, master_url, indexed, args.url, trailer_hint)
                print("-" * 30)
                continue

            year = str(item.get("releaseDate") or "")[0:4] or "0000"

            base_name_raw = "{} - {} ({}) Trailer [WEB-DL] [ATVP] [{}]".format(
                sanitize(item.get("title") or ""),
                sanitize(item.get("videoTitle") or ""),
                year,
                trailer_tag,
            )

            if clip_suffix:
                base_name_raw += f" [clip-{sanitize(clip_suffix)}]"

            # NEW (v2.3.3): sanitize the FULL name as a final guard (Windows/artifact safe)
            base_name = sanitize(base_name_raw)
            if not base_name:
                base_name = "manzana_output"

            op = os.path.join(OUTPUTDIR, base_name + ".mp4")

            # explicit human-readable logs
            logger.info(f'Preparing [{trailer_tag}] {item.get("title","")} | {item.get("videoTitle","")}')
            logger.info(f"Output file: {os.path.basename(op)}")

            if os.path.exists(op):
                logger.info(f'"{os.path.basename(op)}" is already exists! Skipping...')
                print("-" * 30)
                continue

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
