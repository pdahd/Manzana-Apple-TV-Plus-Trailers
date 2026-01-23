# utils/bootstrap_tools.py @ v0.2.2
#
# Runtime tool bootstrap for Manzana (Linux).
#
# v0.2.2 changes vs v0.2.0:
# - Add "debug-gated force bundle" switches:
#     - MANZANA_DEBUG=1 enables debug mode
#     - Only when MANZANA_DEBUG=1, the following force switches take effect:
#         - MANZANA_FORCE_BUNDLE_MP4BOX=1
#         - MANZANA_FORCE_BUNDLE_FFMPEG=1
#   This prevents accidental large downloads in normal user usage.
#
# Default behavior (no debug / no force):
# - Use system MP4Box/ffmpeg if present AND version meets minimal requirement
# - Otherwise download "latest" bundles from this repo Releases and use them (no sudo, no /usr/bin overwrite)
#
# URLs can be overridden:
# - MANZANA_MP4BOX_BUNDLE_BASE
# - MANZANA_FFMPEG_BUNDLE_BASE
#
# Tools directory can be overridden:
# - MANZANA_TOOLS_DIR
# - or XDG_CACHE_HOME (falls back to ~/.cache)

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple

import requests

from utils import logger


# -----------------------------
# Helpers / config
# -----------------------------
def _env_true(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


DEBUG = _env_true("MANZANA_DEBUG")

# Force switches are only effective in debug mode (to avoid accidental heavy downloads)
_FORCE_ENV_MP4BOX = _env_true("MANZANA_FORCE_BUNDLE_MP4BOX")
_FORCE_ENV_FFMPEG = _env_true("MANZANA_FORCE_BUNDLE_FFMPEG")
FORCE_BUNDLE_MP4BOX = DEBUG and _FORCE_ENV_MP4BOX
FORCE_BUNDLE_FFMPEG = DEBUG and _FORCE_ENV_FFMPEG

if (not DEBUG) and (_FORCE_ENV_MP4BOX or _FORCE_ENV_FFMPEG):
    logger.warning(
        "MANZANA_FORCE_BUNDLE_* is set but MANZANA_DEBUG is not enabled; "
        "force switches are ignored. Set MANZANA_DEBUG=1 to enable force mode."
    )

_DEFAULT_MP4BOX_BASE = (
    "https://github.com/pdahd/Manzana-Apple-TV-Plus-Trailers/releases/download/mp4box-bundle-latest"
)
_DEFAULT_FFMPEG_BASE = (
    "https://github.com/pdahd/Manzana-Apple-TV-Plus-Trailers/releases/download/ffmpeg-bundle-latest"
)

MP4BOX_LATEST_BASE = (os.environ.get("MANZANA_MP4BOX_BUNDLE_BASE") or _DEFAULT_MP4BOX_BASE).strip()
FFMPEG_LATEST_BASE = (os.environ.get("MANZANA_FFMPEG_BUNDLE_BASE") or _DEFAULT_FFMPEG_BASE).strip()

MP4BOX_LATEST_TAR_GZ = "mp4box-bundle-linux-x86_64.tar.gz"
MP4BOX_LATEST_TAR_GZ_SHA = MP4BOX_LATEST_TAR_GZ + ".sha256"

FFMPEG_LATEST_TAR_GZ = "ffmpeg-bundle-linux-x86_64.tar.gz"
FFMPEG_LATEST_TAR_GZ_SHA = FFMPEG_LATEST_TAR_GZ + ".sha256"


def _tools_root_dir() -> str:
    v = (os.environ.get("MANZANA_TOOLS_DIR") or "").strip()
    if v:
        return os.path.abspath(os.path.expanduser(v))

    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return os.path.join(os.path.abspath(os.path.expanduser(xdg)), "manzana", "tools")

    return os.path.join(os.path.expanduser("~"), ".cache", "manzana", "tools")


def _run_capture(cmd: list[str]) -> tuple[int, str]:
    import subprocess

    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return p.returncode, (p.stdout or "")
    except Exception as e:
        return 1, str(e)


def _ver_ge(v: Tuple[int, ...], minv: Tuple[int, ...]) -> bool:
    n = max(len(v), len(minv))
    vv = v + (0,) * (n - len(v))
    mm = minv + (0,) * (n - len(minv))
    return vv >= mm


def _read_sha256_from_remote(url: str) -> str:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    text = (r.text or "").strip()
    sha = text.split()[0].strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        raise RuntimeError(f"Invalid sha256 content from {url}: {text[:120]}")
    return sha.lower()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _activate_bin_lib(bin_dir: str, lib_dir: Optional[str] = None) -> None:
    old_path = os.environ.get("PATH") or ""
    os.environ["PATH"] = bin_dir + os.pathsep + old_path

    if lib_dir and os.path.isdir(lib_dir):
        old_ld = os.environ.get("LD_LIBRARY_PATH") or ""
        os.environ["LD_LIBRARY_PATH"] = lib_dir + (os.pathsep + old_ld if old_ld else "")


def _extract_tar_gz_to(src_targz: str, dest_dir: str) -> None:
    # Note: tarfile.extractall can be unsafe on untrusted archives (path traversal).
    # Here we mitigate by enforcing that members stay inside dest_dir.
    def _is_within_directory(directory: str, target: str) -> bool:
        directory = os.path.abspath(directory)
        target = os.path.abspath(target)
        return os.path.commonpath([directory]) == os.path.commonpath([directory, target])

    with tarfile.open(src_targz, "r:gz") as tf:
        for m in tf.getmembers():
            target_path = os.path.join(dest_dir, m.name)
            if not _is_within_directory(dest_dir, target_path):
                raise RuntimeError(f"Unsafe tar member path: {m.name}")
        tf.extractall(dest_dir)


# -----------------------------
# MP4Box (GPAC)
# -----------------------------
def _parse_gpac_version_from_mp4box_output(s: str) -> Optional[Tuple[int, ...]]:
    if not s:
        return None
    m = re.search(r"GPAC\s+version\s+([0-9]+(?:\.[0-9]+)*)", s, re.IGNORECASE)
    if not m:
        return None
    ver = m.group(1)
    try:
        parts = tuple(int(x) for x in ver.split(".") if x.strip().isdigit())
        return parts if parts else None
    except Exception:
        return None


@dataclass
class ToolActivation:
    source: str  # "system" or "bundle"
    mp4box_path: str
    gpac_version: Optional[Tuple[int, ...]]
    bin_dir: Optional[str] = None
    lib_dir: Optional[str] = None


def ensure_mp4box(min_gpac_version: Tuple[int, ...] = (2, 0)) -> ToolActivation:
    arch = platform.machine().lower()
    if arch not in ("x86_64", "amd64"):
        p = shutil.which("MP4Box")
        if not p:
            logger.error(f"MP4Box not found and arch '{arch}' is not supported by auto-bundle yet.", 1)
        rc, out = _run_capture([p, "-version"])
        v = _parse_gpac_version_from_mp4box_output(out) if rc == 0 else None
        if v and _ver_ge(v, min_gpac_version):
            return ToolActivation(source="system", mp4box_path=p, gpac_version=v)
        logger.error(f"MP4Box found but GPAC version too low (need >= {min_gpac_version}).", 1)

    if FORCE_BUNDLE_MP4BOX:
        logger.info("MANZANA_DEBUG=1 + MANZANA_FORCE_BUNDLE_MP4BOX=1 -> forcing bundled MP4Box (skip system check).")
    else:
        sys_mp4 = shutil.which("MP4Box")
        if sys_mp4:
            rc, out = _run_capture([sys_mp4, "-version"])
            v = _parse_gpac_version_from_mp4box_output(out) if rc == 0 else None
            if v and _ver_ge(v, min_gpac_version):
                logger.info(f"Using system MP4Box: {sys_mp4} (GPAC {'.'.join(map(str, v))})")
                return ToolActivation(source="system", mp4box_path=sys_mp4, gpac_version=v)
            logger.warning(
                f"System MP4Box exists but version not OK (need >= {min_gpac_version}). "
                f"Will use bundled MP4Box instead."
            )

    root = _tools_root_dir()
    bundle_dir = os.path.join(root, "mp4box", "latest")
    bin_dir = os.path.join(bundle_dir, "bin")
    lib_dir = os.path.join(bundle_dir, "lib")
    bundle_mp4 = os.path.join(bin_dir, "MP4Box")

    if os.path.isfile(bundle_mp4) and os.path.isdir(lib_dir):
        _activate_bin_lib(bin_dir, lib_dir)
        rc, out = _run_capture([bundle_mp4, "-version"])
        v = _parse_gpac_version_from_mp4box_output(out) if rc == 0 else None
        if v and _ver_ge(v, min_gpac_version):
            logger.info(f"Using cached bundled MP4Box: {bundle_mp4} (GPAC {'.'.join(map(str, v))})")
            return ToolActivation(source="bundle", mp4box_path=bundle_mp4, gpac_version=v, bin_dir=bin_dir, lib_dir=lib_dir)
        logger.warning("Cached MP4Box bundle exists but seems broken or too old; re-downloading...")

    os.makedirs(os.path.join(root, "mp4box"), exist_ok=True)
    url_tar = f"{MP4BOX_LATEST_BASE}/{MP4BOX_LATEST_TAR_GZ}"
    url_sha = f"{MP4BOX_LATEST_BASE}/{MP4BOX_LATEST_TAR_GZ_SHA}"
    logger.info(f"Downloading MP4Box bundle (latest): {url_tar}")

    expected_sha = _read_sha256_from_remote(url_sha)

    fd, tmp_path = tempfile.mkstemp(prefix="manzana-mp4box-", suffix=".tar.gz")
    os.close(fd)
    try:
        with requests.get(url_tar, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        got_sha = _sha256_file(tmp_path)
        if got_sha.lower() != expected_sha.lower():
            raise RuntimeError(f"SHA256 mismatch for mp4box bundle: got={got_sha} expected={expected_sha}")

        parent = os.path.join(root, "mp4box")
        tmp_extract = tempfile.mkdtemp(prefix="latest-", dir=parent)
        try:
            _extract_tar_gz_to(tmp_path, tmp_extract)

            if not os.path.isfile(os.path.join(tmp_extract, "bin", "MP4Box")):
                raise RuntimeError("Bundle tar.gz does not contain bin/MP4Box (unexpected layout).")
            if not os.path.isdir(os.path.join(tmp_extract, "lib")):
                raise RuntimeError("Bundle tar.gz does not contain lib/ (unexpected layout).")

            if os.path.exists(bundle_dir):
                shutil.rmtree(bundle_dir, ignore_errors=True)
            os.replace(tmp_extract, bundle_dir)
            tmp_extract = ""
        finally:
            if tmp_extract and os.path.exists(tmp_extract):
                shutil.rmtree(tmp_extract, ignore_errors=True)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    bin_dir = os.path.join(bundle_dir, "bin")
    lib_dir = os.path.join(bundle_dir, "lib")
    bundle_mp4 = os.path.join(bin_dir, "MP4Box")
    _activate_bin_lib(bin_dir, lib_dir)

    rc, out = _run_capture([bundle_mp4, "-version"])
    v = _parse_gpac_version_from_mp4box_output(out) if rc == 0 else None
    if not (v and _ver_ge(v, min_gpac_version)):
        logger.error("Bundled MP4Box installed, but version check failed.", 1)

    logger.info(f"Bundled MP4Box ready: {bundle_mp4} (GPAC {'.'.join(map(str, v))})")
    return ToolActivation(source="bundle", mp4box_path=bundle_mp4, gpac_version=v, bin_dir=bin_dir, lib_dir=lib_dir)


# -----------------------------
# FFmpeg (BtbN bundle mirror)
# -----------------------------
def _parse_ffmpeg_version_from_output(s: str) -> Optional[Tuple[int, ...]]:
    if not s:
        return None
    line = s.splitlines()[0] if s.splitlines() else s
    m = re.search(r"^ffmpeg\s+version\s+(\S+)", line, re.IGNORECASE)
    if not m:
        return None
    token = m.group(1)
    if token.startswith("N-") or token.lower().startswith("git"):
        return (999, 0, 0)
    m2 = re.match(r"^([0-9]+(?:\.[0-9]+){1,3})", token)
    if not m2:
        return None
    try:
        parts = tuple(int(x) for x in m2.group(1).split("."))
        return parts if parts else None
    except Exception:
        return None


@dataclass
class FFmpegActivation:
    source: str  # "system" or "bundle"
    ffmpeg_path: str
    ffprobe_path: str
    ffmpeg_version: Optional[Tuple[int, ...]]
    bin_dir: Optional[str] = None
    lib_dir: Optional[str] = None


def ensure_ffmpeg(min_ffmpeg_version: Tuple[int, ...] = (4, 2)) -> FFmpegActivation:
    arch = platform.machine().lower()
    if arch not in ("x86_64", "amd64"):
        p = shutil.which("ffmpeg")
        q = shutil.which("ffprobe")
        if not p or not q:
            logger.error(f"ffmpeg/ffprobe not found and arch '{arch}' is not supported by auto-bundle yet.", 1)
        rc, out = _run_capture([p, "-version"])
        v = _parse_ffmpeg_version_from_output(out) if rc == 0 else None
        if v and _ver_ge(v, min_ffmpeg_version):
            logger.info(f"Using system ffmpeg: {p} (ver {'.'.join(map(str, v))})")
            return FFmpegActivation(source="system", ffmpeg_path=p, ffprobe_path=q, ffmpeg_version=v)
        logger.error(f"System ffmpeg found but version too low/unknown (need >= {min_ffmpeg_version}).", 1)

    if FORCE_BUNDLE_FFMPEG:
        logger.info("MANZANA_DEBUG=1 + MANZANA_FORCE_BUNDLE_FFMPEG=1 -> forcing bundled ffmpeg (skip system check).")
    else:
        sys_ff = shutil.which("ffmpeg")
        sys_fp = shutil.which("ffprobe")
        if sys_ff and sys_fp:
            rc, out = _run_capture([sys_ff, "-version"])
            v = _parse_ffmpeg_version_from_output(out) if rc == 0 else None
            if v and _ver_ge(v, min_ffmpeg_version):
                logger.info(f"Using system ffmpeg: {sys_ff} (ver {'.'.join(map(str, v))})")
                return FFmpegActivation(source="system", ffmpeg_path=sys_ff, ffprobe_path=sys_fp, ffmpeg_version=v)
            logger.warning(
                f"System ffmpeg exists but version not OK (need >= {min_ffmpeg_version}). "
                f"Will use bundled ffmpeg instead."
            )

    root = _tools_root_dir()
    bundle_dir = os.path.join(root, "ffmpeg", "latest")
    bin_dir = os.path.join(bundle_dir, "bin")
    lib_dir = os.path.join(bundle_dir, "lib")
    b_ff = os.path.join(bin_dir, "ffmpeg")
    b_fp = os.path.join(bin_dir, "ffprobe")

    if os.path.isfile(b_ff) and os.path.isfile(b_fp):
        _activate_bin_lib(bin_dir, lib_dir if os.path.isdir(lib_dir) else None)
        rc, out = _run_capture([b_ff, "-version"])
        v = _parse_ffmpeg_version_from_output(out) if rc == 0 else None
        if v and _ver_ge(v, min_ffmpeg_version):
            logger.info(f"Using cached bundled ffmpeg: {b_ff}")
            return FFmpegActivation(
                source="bundle",
                ffmpeg_path=b_ff,
                ffprobe_path=b_fp,
                ffmpeg_version=v,
                bin_dir=bin_dir,
                lib_dir=lib_dir if os.path.isdir(lib_dir) else None,
            )
        logger.warning("Cached ffmpeg bundle exists but seems broken/too old; re-downloading...")

    os.makedirs(os.path.join(root, "ffmpeg"), exist_ok=True)
    url_tar = f"{FFMPEG_LATEST_BASE}/{FFMPEG_LATEST_TAR_GZ}"
    url_sha = f"{FFMPEG_LATEST_BASE}/{FFMPEG_LATEST_TAR_GZ_SHA}"
    logger.info(f"Downloading ffmpeg bundle (latest): {url_tar}")

    expected_sha = _read_sha256_from_remote(url_sha)

    fd, tmp_path = tempfile.mkstemp(prefix="manzana-ffmpeg-", suffix=".tar.gz")
    os.close(fd)
    try:
        with requests.get(url_tar, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        got_sha = _sha256_file(tmp_path)
        if got_sha.lower() != expected_sha.lower():
            raise RuntimeError(f"SHA256 mismatch for ffmpeg bundle: got={got_sha} expected={expected_sha}")

        parent = os.path.join(root, "ffmpeg")
        tmp_extract = tempfile.mkdtemp(prefix="latest-", dir=parent)
        try:
            _extract_tar_gz_to(tmp_path, tmp_extract)

            if not os.path.isfile(os.path.join(tmp_extract, "bin", "ffmpeg")):
                raise RuntimeError("FFmpeg bundle tar.gz does not contain bin/ffmpeg (unexpected layout).")
            if not os.path.isfile(os.path.join(tmp_extract, "bin", "ffprobe")):
                raise RuntimeError("FFmpeg bundle tar.gz does not contain bin/ffprobe (unexpected layout).")

            if os.path.exists(bundle_dir):
                shutil.rmtree(bundle_dir, ignore_errors=True)
            os.replace(tmp_extract, bundle_dir)
            tmp_extract = ""
        finally:
            if tmp_extract and os.path.exists(tmp_extract):
                shutil.rmtree(tmp_extract, ignore_errors=True)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    bin_dir = os.path.join(bundle_dir, "bin")
    lib_dir = os.path.join(bundle_dir, "lib")
    b_ff = os.path.join(bin_dir, "ffmpeg")
    b_fp = os.path.join(bin_dir, "ffprobe")

    _activate_bin_lib(bin_dir, lib_dir if os.path.isdir(lib_dir) else None)

    rc, out = _run_capture([b_ff, "-version"])
    v = _parse_ffmpeg_version_from_output(out) if rc == 0 else None
    if not (v and _ver_ge(v, min_ffmpeg_version)):
        logger.error("Bundled ffmpeg installed, but version check failed.", 1)

    logger.info(f"Bundled ffmpeg ready: {b_ff}")
    return FFmpegActivation(
        source="bundle",
        ffmpeg_path=b_ff,
        ffprobe_path=b_fp,
        ffmpeg_version=v,
        bin_dir=bin_dir,
        lib_dir=lib_dir if os.path.isdir(lib_dir) else None,
    )
