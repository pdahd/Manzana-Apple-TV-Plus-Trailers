#!/usr/bin/env bash
set -euo pipefail

# install-manzana.sh @ v0.1.3
#
# Changes vs v0.1.2:
# - Cleaner output by default:
#   - pip install output is redirected to install.log
#   - only prints high-level steps
#   - on failure, prints tail of install.log
# - Add MANZANA_INSTALL_VERBOSE=1 to show full pip output.
# - Keep venv fallback: if ensurepip is missing/disabled, use --without-pip + get-pip.py (no sudo).
#
# Features:
# - Install to user dir (no sudo):
#   - APP_DIR: ~/.local/share/manzana
#   - BIN_DIR: ~/.local/bin (wrapper "manzana")
# - Support installing a specific ref for reproducibility:
#   - MANZANA_REF or --ref
# - Support uninstall:
#   - --uninstall
# - Optionally modify shell rc to include ~/.local/bin:
#   - MANZANA_MODIFY_PATH=1(default), 0=disable

REPO_OWNER="pdahd"
REPO_NAME="Manzana-Apple-TV-Plus-Trailers"

DEFAULT_REF="main"
REF="${MANZANA_REF:-$DEFAULT_REF}"

APP_DIR_DEFAULT="${XDG_DATA_HOME:-$HOME/.local/share}/manzana"
BIN_DIR_DEFAULT="$HOME/.local/bin"

APP_DIR="${MANZANA_APP_DIR:-$APP_DIR_DEFAULT}"
BIN_DIR="${MANZANA_BIN_DIR:-$BIN_DIR_DEFAULT}"

MODIFY_PATH="${MANZANA_MODIFY_PATH:-1}"             # 1=yes, 0=no
VERBOSE="${MANZANA_INSTALL_VERBOSE:-0}"             # 1=yes, 0=no
DEBUG="${MANZANA_DEBUG:-0}"                         # 1=yes, 0=no

say() { printf '%s\n' "$*"; }
die() { say "ERROR: $*"; exit 1; }

usage() {
  cat <<EOF
Manzana installer (v0.1.3)

Usage:
  bash install-manzana.sh [--ref <ref>] [--uninstall]

Options:
  --ref <ref>       Install a specific Git ref (tag/branch/commit). Default: ${DEFAULT_REF}
  --uninstall       Uninstall (remove wrapper + app dir)

Env vars:
  MANZANA_REF                 Same as --ref
  MANZANA_APP_DIR             Default: ${APP_DIR_DEFAULT}
  MANZANA_BIN_DIR             Default: ${BIN_DIR_DEFAULT}
  MANZANA_MODIFY_PATH         1(default)=append PATH export to ~/.bashrc and/or ~/.zshrc, 0=do not modify rc files
  MANZANA_INSTALL_VERBOSE     1=show full pip output, 0(default)=write to install.log
  MANZANA_DEBUG               1=print extra debug output
EOF
}

ACTION="install"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      shift
      [[ $# -gt 0 ]] || die "--ref requires a value"
      REF="$1"
      shift
      ;;
    --uninstall)
      ACTION="uninstall"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1 (use --help)"
      ;;
  esac
done

# downloader
if command -v curl >/dev/null 2>&1; then
  DL="curl"
elif command -v wget >/dev/null 2>&1; then
  DL="wget"
else
  die "Need curl or wget"
fi

download_to() {
  local url="$1"
  local out="$2"
  if [[ "$DL" == "curl" ]]; then
    curl -fsSL --retry 3 --retry-delay 2 "$url" -o "$out"
  else
    wget -qO "$out" "$url"
  fi
}

say "== Manzana installer =="
say "Repo: ${REPO_OWNER}/${REPO_NAME}"
say "Ref:  ${REF}"
say "Install dir: $APP_DIR"
say "Bin dir:     $BIN_DIR"
say "Action:      $ACTION"
say ""

if [[ "$ACTION" == "uninstall" ]]; then
  say "Uninstalling..."
  rm -f "$BIN_DIR/manzana" 2>/dev/null || true
  rm -rf "$APP_DIR" 2>/dev/null || true
  say "Removed:"
  say " - $BIN_DIR/manzana"
  say " - $APP_DIR"
  say ""
  say "Optional cleanup (not automatic):"
  say " - Tool cache: ~/.cache/manzana/tools (or MANZANA_TOOLS_DIR if you set it)"
  say " - PATH lines in ~/.bashrc / ~/.zshrc (if added)"
  exit 0
fi

command -v python3 >/dev/null 2>&1 || die "Missing python3"

if ! python3 -c 'import venv' >/dev/null 2>&1; then
  die "python3 venv module not available. On Debian/Ubuntu: sudo apt-get install -y python3-venv"
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

TARBALL_CANDIDATES=(
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${REF}.tar.gz"
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REF}.tar.gz"
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/${REF}.tar.gz"
)

say "Downloading source tarball..."
SRC_TAR="$TMP/src.tar.gz"
DOWNLOADED=0
for u in "${TARBALL_CANDIDATES[@]}"; do
  [[ "$DEBUG" == "1" ]] && say "  trying: $u"
  if download_to "$u" "$SRC_TAR" >/dev/null 2>&1; then
    say "ok: $u"
    DOWNLOADED=1
    break
  fi
done
[[ "$DOWNLOADED" -eq 1 ]] || die "Unable to download tarball for ref '$REF' (tried tags/heads/commit)."

say "Extracting..."
mkdir -p "$TMP/src"
tar -xzf "$SRC_TAR" -C "$TMP/src"

SRC_DIR="$(find "$TMP/src" -maxdepth 1 -type d -name "${REPO_NAME}-*" | head -n 1 || true)"
[[ -n "$SRC_DIR" && -d "$SRC_DIR" ]] || die "Unable to locate extracted source directory."

say "Installing files..."
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/venv" "$APP_DIR/src" 2>/dev/null || true
mkdir -p "$APP_DIR/src"
cp -a "$SRC_DIR"/. "$APP_DIR/src/"

INSTALL_LOG="$APP_DIR/install.log"
mkdir -p "$APP_DIR"
: > "$INSTALL_LOG"

say "Creating virtualenv..."
VENV_ERR="$TMP/venv.err"
set +e
python3 -m venv "$APP_DIR/venv" >/dev/null 2>"$VENV_ERR"
VENV_RC=$?
set -e

if [[ $VENV_RC -ne 0 ]]; then
  say "INFO: venv ensurepip not available; using --without-pip + get-pip.py fallback."
  [[ "$DEBUG" == "1" ]] && { say "--- venv stderr ---"; sed -n '1,120p' "$VENV_ERR" || true; say "--- end ---"; }

  rm -rf "$APP_DIR/venv" 2>/dev/null || true
  python3 -m venv --without-pip "$APP_DIR/venv"

  say "Bootstrapping pip via get-pip.py..."
  GETPIP_URL="https://bootstrap.pypa.io/get-pip.py"
  GETPIP_PY="$TMP/get-pip.py"
  download_to "$GETPIP_URL" "$GETPIP_PY"
  "$APP_DIR/venv/bin/python" "$GETPIP_PY" >>"$INSTALL_LOG" 2>&1
fi

[[ -x "$APP_DIR/venv/bin/python" ]] || die "venv python not found: $APP_DIR/venv/bin/python"

say "Installing python deps..."
if [[ "$VERBOSE" == "1" ]]; then
  "$APP_DIR/venv/bin/python" -m pip install --upgrade pip
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/src/requirements.txt"
else
  {
    "$APP_DIR/venv/bin/python" -m pip install --upgrade pip
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/src/requirements.txt"
  } >>"$INSTALL_LOG" 2>&1 || {
    say "ERROR: pip install failed. Showing last 80 lines of install.log:"
    tail -n 80 "$INSTALL_LOG" || true
    die "pip install failed (full log: $INSTALL_LOG)"
  }
fi

say "Creating wrapper command: manzana"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/manzana" <<SH
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR}"
exec "\$APP_DIR/venv/bin/python" "\$APP_DIR/src/manzana.py" "\$@"
SH
chmod +x "$BIN_DIR/manzana"

# Modify PATH in rc files (for future shells)
maybe_add_path_rc() {
  [[ "$MODIFY_PATH" == "1" ]] || return 0

  local line='export PATH="$HOME/.local/bin:$PATH"'
  local marker='# Added by Manzana installer (ensure ~/.local/bin is on PATH)'
  local targets=()
  [[ -f "$HOME/.bashrc" ]] && targets+=("$HOME/.bashrc")
  [[ -f "$HOME/.zshrc" ]] && targets+=("$HOME/.zshrc")
  [[ ${#targets[@]} -eq 0 ]] && targets+=("$HOME/.bashrc")

  for rc in "${targets[@]}"; do
    if [[ -f "$rc" ]] && grep -qF "$line" "$rc"; then
      continue
    fi
    {
      echo ""
      echo "$marker"
      echo "$line"
    } >> "$rc"
  done
}

maybe_add_path_rc

say ""
say "== Done =="
say "Run (current shell):"
say "  export PATH=\"\$HOME/.local/bin:\$PATH\""
say "  manzana --help"
say ""
say "For future shells, PATH was written to rc file(s) (if enabled)."
say "Install log: $INSTALL_LOG"
