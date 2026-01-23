# utils/bootstrap_tools.py @ v0.1.0
#
# Runtime tool bootstrap for Manzana (Linux).
#
# Current scope:
# - ensure_mp4box(): if system MP4Box exists and gpac >= min, use it.
#   Otherwise download a prebuilt bundle from GitHub Releases (mp4box-bundle-latest),
#   verify sha256, extract into user cache dir, and activate via PATH + LD_LIBRARY_PATH.
#
# Notes:
# - We DO NOT overwrite /usr/bin. We only manage our own cache directory.
# - This module is safe for CI/tool scripts because those scripts redirect Manzana logger console to stderr.

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

# --- Config (stable URLs) ---
MP4BOX_LATEST_BASE = (
    "https://github.com/pdahd/Manzana-Apple-TV-Plus-Trailers/releases/download/mp4box-bundle-latest"
)
MP4BOX_LATEST_TAR_GZ = "mp4box-bundle-linux-x86_64.tar.gz"
MP4BOX_LATEST_TAR_GZ_SHA = MP4BOX_LATEST_TAR_GZ + ".sha256"


def _tools_root_dir() -> str:
    # Allow override
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


def _parse_gpac_version_from_mp4box_output(s: str) -> Optional[Tuple[int, ...]]:
    """
    Parse from:
      "MP4Box - GPAC version 2.0-rev2.0.0+dfsg1-2"
      "GPAC version 2.2.1-..."
    We only care about the leading numeric dotted version: 2.0 / 2.2.1 etc.
    """
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


def _ver_ge(v: Tuple[int, ...], minv: Tuple[int, ...]) -> bool:
    # Compare lexicographically with padding
    n = max(len(v), len(minv))
    vv = v + (0,) * (n - len(v))
    mm = minv + (0,) * (n - len(minv))
    return vv >= mm


@dataclass
class ToolActivation:
    source: str  # "system" or "bundle"
    mp4box_path: str
    gpac_version: Optional[Tuple[int, ...]]
    bin_dir: Optional[str] = None
    lib_dir: Optional[str] = None


def _activate_bin_lib(bin_dir: str, lib_dir: str) -> None:
    # Prepend PATH
    old_path = os.environ.get("PATH") or ""
    os.environ["PATH"] = bin_dir + os.pathsep + old_path

    # Prepend LD_LIBRARY_PATH
    old_ld = os.environ.get("LD_LIBRARY_PATH") or ""
    if old_ld:
        os.environ["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + old_ld
    else:
        os.environ["LD_LIBRARY_PATH"] = lib_dir


def _read_sha256_from_remote(url: str) -> str:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    text = (r.text or "").strip()
    # accept formats: "<sha>  file" or "<sha>" only
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


def ensure_mp4box(min_gpac_version: Tuple[int, ...] = (2, 0)) -> ToolActivation:
    """
    Ensure MP4Box exists and meets minimal GPAC version.
    Returns activation info, and mutates process env (PATH/LD_LIBRARY_PATH) if using bundle.
    """
    arch = platform.machine().lower()
    if arch not in ("x86_64", "amd64"):
        # Future: add aarch64 assets. For now, fail softly: use system only.
        p = shutil.which("MP4Box")
        if not p:
            logger.error(f"MP4Box not found and arch '{arch}' is not supported by auto-bundle yet.", 1)
        rc, out = _run_capture([p, "-version"])
        v = _parse_gpac_version_from_mp4box_output(out) if rc == 0 else None
        if v and _ver_ge(v, min_gpac_version):
            return ToolActivation(source="system", mp4box_path=p, gpac_version=v)
        logger.error(f"MP4Box found but GPAC version too low (need >= {min_gpac_version}).", 1)

    # 1) Try system MP4Box first
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

    # 2) Use cached bundle if present and valid
    root = _tools_root_dir()
    bundle_dir = os.path.join(root, "mp4box", "latest")
    bin_dir = os.path.join(bundle_dir, "bin")
    lib_dir = os.path.join(bundle_dir, "lib")
    bundle_mp4 = os.path.join(bin_dir, "MP4Box")

    if os.path.isfile(bundle_mp4) and os.path.isdir(lib_dir):
        # Activate and verify
        _activate_bin_lib(bin_dir, lib_dir)
        rc, out = _run_capture([bundle_mp4, "-version"])
        v = _parse_gpac_version_from_mp4box_output(out) if rc == 0 else None
        if v and _ver_ge(v, min_gpac_version):
            logger.info(f"Using cached bundled MP4Box: {bundle_mp4} (GPAC {'.'.join(map(str, v))})")
            return ToolActivation(source="bundle", mp4box_path=bundle_mp4, gpac_version=v, bin_dir=bin_dir, lib_dir=lib_dir)

        logger.warning("Cached MP4Box bundle exists but seems broken or too old; re-downloading...")

    # 3) Download latest tar.gz + sha256 and install
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

        # Extract to temp dir then atomic replace
        parent = os.path.join(root, "mp4box")
        tmp_extract = tempfile.mkdtemp(prefix="latest-", dir=parent)

        try:
            with tarfile.open(tmp_path, "r:gz") as tf:
                tf.extractall(tmp_extract)

            # Validate expected layout
            if not os.path.isfile(os.path.join(tmp_extract, "bin", "MP4Box")):
                raise RuntimeError("Bundle tar.gz does not contain bin/MP4Box (unexpected layout).")
            if not os.path.isdir(os.path.join(tmp_extract, "lib")):
                raise RuntimeError("Bundle tar.gz does not contain lib/ (unexpected layout).")

            # Replace current
            if os.path.exists(bundle_dir):
                shutil.rmtree(bundle_dir, ignore_errors=True)
            os.replace(tmp_extract, bundle_dir)  # atomic rename within same filesystem
            tmp_extract = ""  # moved

        finally:
            if tmp_extract and os.path.exists(tmp_extract):
                shutil.rmtree(tmp_extract, ignore_errors=True)

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    # Activate and verify installed bundle
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
