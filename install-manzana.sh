#!/usr/bin/env bash
set -euo pipefail

# install-manzana.sh @ v0.1.4
#
# Changes vs v0.1.3:
# - Wrapper now exports MANZANA_INSTALL=1 so installed CLI defaults output dir to:
#     当前工作目录/video  （若当前目录无写权限则回退到 ~/video）
#   (Requires core/control.py @ v2.4.4 to be present in the installed source.)
# - Improve user-facing messages (Chinese-friendly).
#
# Keeps v0.1.3 features:
# - Clean output by default; pip output goes to install.log (verbose switch available)
# - Robust venv creation: fallback to --without-pip + get-pip.py if ensurepip missing/disabled
# - Install a specific ref (tag/branch/commit): MANZANA_REF or --ref
# - Uninstall: --uninstall
# - Optionally append ~/.local/bin to PATH via rc files (MANZANA_MODIFY_PATH=1 default)

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
Manzana 安装脚本 (v0.1.4)

用法：
  bash install-manzana.sh [--ref <ref>] [--uninstall]

参数：
  --ref <ref>       安装指定版本（tag/branch/commit）。默认：${DEFAULT_REF}
  --uninstall       卸载（删除命令 + 安装目录）

环境变量：
  MANZANA_REF                 同 --ref
  MANZANA_APP_DIR             默认：${APP_DIR_DEFAULT}
  MANZANA_BIN_DIR             默认：${BIN_DIR_DEFAULT}
  MANZANA_MODIFY_PATH         1(默认)=写入 ~/.bashrc / ~/.zshrc 以加入 ~/.local/bin，0=不修改
  MANZANA_INSTALL_VERBOSE     1=显示 pip 全量输出，0(默认)=写入 install.log 保持整洁
  MANZANA_DEBUG               1=输出更多调试信息

说明：
- 本脚本不需要 sudo，安装到用户目录。
- ffmpeg / MP4Box 不会系统级安装；Manzana 运行时会按需自动下载工具包到缓存目录。
EOF
}

ACTION="install"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      shift
      [[ $# -gt 0 ]] || die "--ref 需要一个值"
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
      die "未知参数：$1（使用 --help 查看用法）"
      ;;
  esac
done

# downloader
if command -v curl >/dev/null 2>&1; then
  DL="curl"
elif command -v wget >/dev/null 2>&1; then
  DL="wget"
else
  die "缺少 curl 或 wget"
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

say "== Manzana 安装器 =="
say "仓库：${REPO_OWNER}/${REPO_NAME}"
say "版本(ref)：${REF}"
say "安装目录：$APP_DIR"
say "命令目录：$BIN_DIR"
say "动作：$ACTION"
say ""

if [[ "$ACTION" == "uninstall" ]]; then
  say "开始卸载..."
  rm -f "$BIN_DIR/manzana" 2>/dev/null || true
  rm -rf "$APP_DIR" 2>/dev/null || true
  say "已删除："
  say " - $BIN_DIR/manzana"
  say " - $APP_DIR"
  say ""
  say "可选清理（脚本不会自动删除）："
  say " - 工具缓存：~/.cache/manzana/tools（或你设置的 MANZANA_TOOLS_DIR）"
  say " - ~/.bashrc / ~/.zshrc 里由安装器写入的 PATH 行（如有）"
  exit 0
fi

command -v python3 >/dev/null 2>&1 || die "缺少 python3"
if ! python3 -c 'import venv' >/dev/null 2>&1; then
  die "当前 python3 缺少 venv 模块。Debian/Ubuntu 通常需要安装 python3-venv（可能需要 sudo）。"
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# Try refs: tags -> heads -> commit/archive
TARBALL_CANDIDATES=(
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/tags/${REF}.tar.gz"
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REF}.tar.gz"
  "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/${REF}.tar.gz"
)

say "下载源码包..."
SRC_TAR="$TMP/src.tar.gz"
DOWNLOADED=0
for u in "${TARBALL_CANDIDATES[@]}"; do
  [[ "$DEBUG" == "1" ]] && say "  尝试：$u"
  if download_to "$u" "$SRC_TAR" >/dev/null 2>&1; then
    say "  成功：$u"
    DOWNLOADED=1
    break
  fi
done
[[ "$DOWNLOADED" -eq 1 ]] || die "下载失败：ref='$REF'（已尝试 tag/branch/commit 三种 URL）"

say "解压..."
mkdir -p "$TMP/src"
tar -xzf "$SRC_TAR" -C "$TMP/src"

SRC_DIR="$(find "$TMP/src" -maxdepth 1 -type d -name "${REPO_NAME}-*" | head -n 1 || true)"
[[ -n "$SRC_DIR" && -d "$SRC_DIR" ]] || die "无法定位解压后的源码目录"

say "写入安装目录..."
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/venv" "$APP_DIR/src" 2>/dev/null || true
mkdir -p "$APP_DIR/src"
cp -a "$SRC_DIR"/. "$APP_DIR/src/"

INSTALL_LOG="$APP_DIR/install.log"
: > "$INSTALL_LOG"

say "创建虚拟环境(venv)..."
VENV_ERR="$TMP/venv.err"
set +e
python3 -m venv "$APP_DIR/venv" >/dev/null 2>"$VENV_ERR"
VENV_RC=$?
set -e

if [[ $VENV_RC -ne 0 ]]; then
  say "提示：当前环境 ensurepip 不可用，改用 --without-pip + get-pip.py 方案（不影响安装）。"
  [[ "$DEBUG" == "1" ]] && { say "--- venv 错误输出（前 120 行）---"; sed -n '1,120p' "$VENV_ERR" || true; say "--- end ---"; }

  rm -rf "$APP_DIR/venv" 2>/dev/null || true
  python3 -m venv --without-pip "$APP_DIR/venv"

  say "引导安装 pip（get-pip.py）..."
  GETPIP_URL="https://bootstrap.pypa.io/get-pip.py"
  GETPIP_PY="$TMP/get-pip.py"
  download_to "$GETPIP_URL" "$GETPIP_PY"
  "$APP_DIR/venv/bin/python" "$GETPIP_PY" >>"$INSTALL_LOG" 2>&1
fi

[[ -x "$APP_DIR/venv/bin/python" ]] || die "venv 创建失败：找不到 $APP_DIR/venv/bin/python"

say "安装 Python 依赖..."
if [[ "$VERBOSE" == "1" ]]; then
  "$APP_DIR/venv/bin/python" -m pip install --upgrade pip
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/src/requirements.txt"
else
  {
    "$APP_DIR/venv/bin/python" -m pip install --upgrade pip
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/src/requirements.txt"
  } >>"$INSTALL_LOG" 2>&1 || {
    say "ERROR: 依赖安装失败。以下是 install.log 的最后 80 行："
    tail -n 80 "$INSTALL_LOG" || true
    die "pip install 失败（完整日志：$INSTALL_LOG）"
  }
fi

say "生成命令：manzana"
mkdir -p "$BIN_DIR"

# IMPORTANT: mark installed CLI mode for friendly output directory behavior
cat > "$BIN_DIR/manzana" <<SH
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR}"

# 安装版运行标记：让 Manzana 默认输出到“当前目录/video”
# （若当前目录不可写，会自动回退到 ~/video）
export MANZANA_INSTALL=1

exec "\$APP_DIR/venv/bin/python" "\$APP_DIR/src/manzana.py" "\$@"
SH
chmod +x "$BIN_DIR/manzana"

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
say "== 安装完成 =="
say "当前终端立即使用："
say "  export PATH=\"\$HOME/.local/bin:\$PATH\""
say "  manzana --help"
say ""
say "安装版默认输出目录："
say "  当前目录/video   （若当前目录无写权限则回退到 ~/video）"
say ""
say "提示：已尝试写入 rc 文件（~/.bashrc 或 ~/.zshrc）以便以后新开终端自动生效。"
say "安装日志：$INSTALL_LOG"
