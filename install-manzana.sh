#!/usr/bin/env bash
set -euo pipefail

# install-manzana.sh @ v0.1.2
#
# Key features:
# - Install Manzana into user directory (no sudo):
#     - APP_DIR: ~/.local/share/manzana
#     - BIN_DIR: ~/.local/bin (wrapper command "manzana")
# - Robust venv creation:
#     - Try python3 -m venv (may fail if ensurepip is disabled)
#     - Fallback to python3 -m venv --without-pip + get-pip.py
# - Support installing a specific ref (tag/branch/commit) for reproducibility:
#     - MANZANA_REF or --ref
# - Support uninstall:
#     - --uninstall
# - Optionally modify shell rc to include ~/.local/bin so user can run `manzana` directly:
#     - default: enabled (MANZANA_MODIFY_PATH=1)
#     - disable: MANZANA_MODIFY_PATH=0

REPO_OWNER="pdahd"
REPO_NAME="Manzana-Apple-TV-Plus-Trailers"

DEFAULT_REF="main"
REF="${MANZANA_REF:-$DEFAULT_REF}"

APP_DIR_DEFAULT="${XDG_DATA_HOME:-$HOME/.local/share}/manzana"
BIN_DIR_DEFAULT="$HOME/.local/bin"

APP_DIR="${MANZANA_APP_DIR:-$APP_DIR_DEFAULT}"
BIN_DIR="${MANZANA_BIN_DIR:-$BIN_DIR_DEFAULT}"

MODIFY_PATH="${MANZANA_MODIFY_PATH:-1}"   # 1=yes, 0=no
DEBUG="${MANZANA_DEBUG:-0}"               # 1=yes, 0=no

say() { printf '%s\n' "$*"; }
die() { say "ERROR: $*"; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

usage() {
  cat <<EOF
Manzana installer (v0.1.2)

Usage:
  bash install-manzana.sh [--ref <ref>] [--uninstall]

Options:
  --ref <ref>       Install a specific Git ref (tag/branch/commit). Default: ${DEFAULT_REF}
  --uninstall       Uninstall (remove wrapper + app dir)

Env vars:
  MANZANA_REF            Same as --ref
  MANZANA_APP_DIR        Default: ${APP_DIR_DEFAULT}
  MANZANA_BIN_DIR        Default: ${BIN_DIR_DEFAULT}
  MANZANA_MODIFY_PATH    1(default)=append PATH export to ~/.bashrc and/or ~/.zshrc, 0=do not modify rc files
  MANZANA_DEBUG          1=print extra debug output

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

if command -v curl >/dev/null 2>&1; then
  DL_CURL="curl"
elif command -v wget >/dev/null 2>&1; then
  DL_CURL="wget"
else
  die "Need curl or wget"
fi

download_to() {
  local url="$1"
  local out="$2"
  if [[ "$DL_CURL" == "curl" ]]; then
    curl -fsSL --retry 3 --retry-delay 2 "$url" -o "$out"
  else
    wget -qO "$out" "$url"
  fi
}

download_stdout() {
  local url="$1"
  if [[ "$DL_CURL" == "curl" ]]; then
    curl -fsSL --retry 3 --retry-delay 2 "$url"
  else
    wget -qO- "$url"
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
  say " - Tool cache: ~/.cache/manzana/tools  (or MANZANA_TOOLS_DIR if you set it)"
  say " - PATH lines in ~/.bashrc / ~/.zshrc (if added)"
  exit 0
fi

need_cmd python3

# venv module required, but on some systems ensurepip is disabled.
if ! python3 -c 'import venv' >/dev/null 2>&1; then
  die "python3 venv module not available. On Debian/Ubuntu: sudo apt-get install -y python3-venv"
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# Try refs in a robust order: tags -> heads -> commit/archive
TARBALL_CANDIDATES=(
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${REF}.tar.gz"
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REF}.tar.gz"
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/${REF}.tar.gz"
)

say "Downloading source tarball..."
SRC_TAR="$TMP/src.tar.gz"
DOWNLOADED=0
for u in "${TARBALL_CANDIDATES[@]}"; do
  if [[ "$DEBUG" == "1" ]]; then
    say "  trying: $u"
  fi
  if download_to "$u" "$SRC_TAR" >/dev/null 2>&1; then
    say "  ok: $u"
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
rm -rf "$APP_DIR/venv" 2>/dev/null || true
rm -rf "$APP_DIR/src" 2>/dev/null || true
mkdir -p "$APP_DIR/src"
cp -a "$SRC_DIR"/. "$APP_DIR/src/"

say "Creating virtualenv..."
VENV_ERR="$TMP/venv.err"
set +e
python3 -m venv "$APP_DIR/venv" >/dev/null 2>"$VENV_ERR"
VENV_RC=$?
set -e

if [[ $VENV_RC -ne 0 ]]; then
  say "WARN: python3 -m venv failed (ensurepip may be missing/disabled). Falling back to --without-pip + get-pip.py."
  if [[ "$DEBUG" == "1" ]]; then
    say "--- venv stderr ---"
    sed -n '1,120p' "$VENV_ERR" || true
    say "--- end ---"
  fi

  rm -rf "$APP_DIR/venv" 2>/dev/null || true
  python3 -m venv --without-pip "$APP_DIR/venv"

  say "Bootstrapping pip via get-pip.py..."
  GETPIP_URL="https://bootstrap.pypa.io/get-pip.py"
  GETPIP_PY="$TMP/get-pip.py"
  download_to "$GETPIP_URL" "$GETPIP_PY"
  "$APP_DIR/venv/bin/python" "$GETPIP_PY" >/dev/null
fi

if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
  die "venv python not found: $APP_DIR/venv/bin/python"
fi

say "Installing python deps..."
"$APP_DIR/venv/bin/python" -m pip install --upgrade pip >/dev/null
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/src/requirements.txt"

say "Creating wrapper command: manzana"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/manzana" <<SH
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR}"
exec "\$APP_DIR/venv/bin/python" "\$APP_DIR/src/manzana.py" "\$@"
SH
chmod +x "$BIN_DIR/manzana"

# Modify PATH in rc files so user can run `manzana` directly
maybe_add_path_rc() {
  [[ "$MODIFY_PATH" == "1" ]] || return 0

  # If already in PATH, no need to touch rc
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) return 0 ;;
  esac

  local line='export PATH="$HOME/.local/bin:$PATH"'
  local marker='# Added by Manzana installer (ensure ~/.local/bin is on PATH)'

  # Prefer writing to existing rc; if none exists, create ~/.bashrc as a default.
  local targets=()
  [[ -f "$HOME/.bashrc" ]] && targets+=("$HOME/.bashrc")
  [[ -f "$HOME/.zshrc" ]] && targets+=("$HOME/.zshrc")

  if [[ ${#targets[@]} -eq 0 ]]; then
    targets+=("$HOME/.bashrc")
  fi

  for rc in "${targets[@]}"; do
    # Avoid duplicate insert
    if [[ -f "$rc" ]] && grep -qF "$line" "$rc"; then
      continue
    fi
    {
      echo ""
      echo "$marker"
      echo "$line"
    } >> "$rc"
  done

  say ""
  say "PATH update:"
  say "  Added ~/.local/bin to PATH in: ${targets[*]}"
  say "  Open a new terminal, or run:"
  say "    export PATH=\"\$HOME/.local/bin:\$PATH\""
}

maybe_add_path_rc

say ""
say "== Done =="
say "Run:"
say "  $BIN_DIR/manzana --help"
say ""
say "Tip: if command not found in current shell, run:"
say "  export PATH=\"\$HOME/.local/bin:\$PATH\""
