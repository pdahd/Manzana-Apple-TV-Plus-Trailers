#!/usr/bin/env bash
set -euo pipefail

# install-manzana.sh @ v0.1.1
#
# Changes vs v0.1.0:
# - Fix venv creation failure on environments where ensurepip is missing/disabled (e.g. some Colab images):
#   - Try normal: python3 -m venv <venv>
#   - If it fails, retry: python3 -m venv --without-pip <venv>
#   - Then bootstrap pip inside venv via get-pip.py (no sudo).
#
# Purpose:
# - One-liner installer for Manzana on Linux (user-space, no sudo).
# - Installs repo snapshot + python venv + wrapper command "manzana" into ~/.local.
#
# Default install locations:
# - APP_DIR:  ~/.local/share/manzana
# - BIN_DIR:  ~/.local/bin

REPO_OWNER="pdahd"
REPO_NAME="Manzana-Apple-TV-Plus-Trailers"
REPO_BRANCH="${MANZANA_BRANCH:-main}"

APP_DIR_DEFAULT="${XDG_DATA_HOME:-$HOME/.local/share}/manzana"
BIN_DIR_DEFAULT="$HOME/.local/bin"

APP_DIR="${MANZANA_APP_DIR:-$APP_DIR_DEFAULT}"
BIN_DIR="${MANZANA_BIN_DIR:-$BIN_DIR_DEFAULT}"

TARBALL_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REPO_BRANCH}.tar.gz"

say() { printf '%s\n' "$*"; }
die() { say "ERROR: $*"; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

say "== Manzana installer =="
say "Repo: ${REPO_OWNER}/${REPO_NAME} (${REPO_BRANCH})"
say "Install dir: $APP_DIR"
say "Bin dir:     $BIN_DIR"
say ""

need_cmd python3

if command -v curl >/dev/null 2>&1; then
  DL="curl -fsSL"
elif command -v wget >/dev/null 2>&1; then
  DL="wget -qO-"
else
  die "Need curl or wget"
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

say "Downloading source tarball..."
$DL "$TARBALL_URL" > "$TMP/src.tar.gz"

say "Extracting..."
mkdir -p "$TMP/src"
tar -xzf "$TMP/src.tar.gz" -C "$TMP/src"

SRC_DIR="$(find "$TMP/src" -maxdepth 1 -type d -name "${REPO_NAME}-*" | head -n 1 || true)"
[[ -n "$SRC_DIR" && -d "$SRC_DIR" ]] || die "Unable to locate extracted source directory."

say "Installing files..."
mkdir -p "$APP_DIR"
# Rebuild venv each time to keep dependencies consistent
rm -rf "$APP_DIR/venv" 2>/dev/null || true
rm -rf "$APP_DIR/src" 2>/dev/null || true
mkdir -p "$APP_DIR/src"
cp -a "$SRC_DIR"/. "$APP_DIR/src/"

say "Creating virtualenv..."
set +e
python3 -m venv "$APP_DIR/venv"
VENV_RC=$?
set -e

if [[ $VENV_RC -ne 0 ]]; then
  say "WARN: python3 -m venv failed (ensurepip may be missing/disabled). Retrying with --without-pip + get-pip.py..."
  rm -rf "$APP_DIR/venv" 2>/dev/null || true

  python3 -m venv --without-pip "$APP_DIR/venv"

  # Bootstrap pip inside venv (no sudo)
  say "Bootstrapping pip via get-pip.py..."
  GETPIP_URL="https://bootstrap.pypa.io/get-pip.py"
  $DL "$GETPIP_URL" > "$TMP/get-pip.py"

  "$APP_DIR/venv/bin/python" "$TMP/get-pip.py" >/dev/null
fi

# Sanity check
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

say ""
say "== Done =="
say "Run:"
say "  $BIN_DIR/manzana --help"
say ""
say "If 'manzana' command not found, add ~/.local/bin to PATH, e.g.:"
say "  echo 'export PATH=\$HOME/.local/bin:\$PATH' >> ~/.bashrc && source ~/.bashrc"
