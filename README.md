<!-- README.md @ v1.8.3
更新说明：
- 明确说明“自动依赖自举（MP4Box/FFmpeg）”的适用范围与限制条件，避免用户误解。
- 说明克隆源码运行与安装版运行在下载阶段使用同一套依赖判断逻辑。
-->

# Manzana（Apple TV+ 预告片下载器）

Manzana 用于下载 Apple TV+ 页面中的预告片/花絮/片段（Trailers/Clips/Teaser）。  
支持列出可用的视频/音频/字幕轨道，并按你的选择下载分片、合并输出 MP4 文件。

本仓库增强特性（相对原作者）：
- GitHub Actions 一键运行
- 非交互式（脚本化/CI）运行方式（类似 yt-dlp 的 `-F / -f`）
- Linux 下自动依赖自举：缺少或版本过旧时自动下载并使用 **MP4Box/FFmpeg**（不覆盖系统 `/usr/bin`）
- 安装版默认输出到当前目录 `./video/`，便于用户查找

---

## 术语说明
- **交互式（Interactive）**：程序会提示并等待输入（选择 trailer、选择轨道 ID 等），适合手动操作。
- **非交互式（Non-interactive）**：不提示、不等待输入；参数一次性给全，适合脚本/CI。常用 `--no-prompt` 与 `-f`。

---

## 三种使用入口（选择其一）

### 入口 A：GitHub Actions（网页运行）
适合不想本地配置环境的用户。  
在仓库页面打开 **Actions** → 运行 `Manzana Download (Apple TV+ Trailers)`，按表单填写 URL、trailer、preset/custom 等参数即可。

> 注意：Actions workflow 中的 ffmpeg/mp4box 安装与缓存逻辑已优化，建议保持现状。

---

### 入口 B：克隆仓库后本地运行（源码方式，兼容原作者用法）
适合想直接运行源码、或进行二次开发的用户。  
输出目录（源码方式）：默认 `./output/`

#### B1. 基础依赖（必需）
- Git（用于 clone）
- Python 3 + pip

在 Debian/Ubuntu 上可参考（可选，按需执行）：
```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-pip
```

#### B2. 克隆并安装 Python 依赖
```bash
git clone https://github.com/pdahd/Manzana-Apple-TV-Plus-Trailers.git
cd Manzana-Apple-TV-Plus-Trailers

python3 -m pip install --upgrade pip
pip3 install -r requirements.txt
```

#### B3. 运行方式（交互式 / 非交互式）
示例 URL：
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

**交互式（Interactive）**：在真实终端（TTY）中执行（不加 `--no-prompt`）
```bash
python3 manzana.py "$URL"
```

**非交互式（Non-interactive）**：脚本化方式（推荐先 -F 再 -f）
```bash
python3 manzana.py --list-trailers "$URL"
python3 manzana.py --no-prompt --trailer t0 -F "$URL"
python3 manzana.py --no-prompt --trailer t0 -f "v0+a0" "$URL"
python3 manzana.py --no-prompt --trailer t0 -f "v0+a0+s0" "$URL"
```

#### B4. 系统依赖（可选：也可以不装，让程序自动自举）
Manzana 合并输出 MP4 需要 MP4Box（GPAC），字幕转换需要 FFmpeg。

在满足“自动依赖自举适用范围”（见下文）的 Linux 环境中：
- 你通常不需要手动安装 ffmpeg/gpac
- 程序会在下载阶段自动判断：系统有合格版本则用系统，否则下载 bundle 使用

如果你希望完全使用系统包管理器安装（可选）：
```bash
sudo apt-get install -y ffmpeg gpac
```

---

### 入口 C：一键安装（推荐：终端安装后直接使用 `manzana` 命令）
适合在 Linux 虚拟机/服务器/容器中快速使用，不需要 sudo。

**一条命令安装并立即可用：**
```bash
export PATH="$HOME/.local/bin:$PATH"; curl -fsSL https://raw.githubusercontent.com/pdahd/Manzana-Apple-TV-Plus-Trailers/main/install-manzana.sh | bash
```

安装完成后：
```bash
manzana --help
```

输出目录（安装版）：
- 默认输出到：当前工作目录 `./video/`
- 若当前目录不可写，则回退到：`~/video`
- 每次下载会打印完整输出路径（以日志为准）

---

## 快速上手（推荐流程）
示例 URL：
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

### 1）列出该页面有哪些视频（t0/t1/t2...）
```bash
manzana --list-trailers "$URL"
```

### 2）列出轨道（formats）并获得轨道 ID（vN/aN/sN）
```bash
manzana --no-prompt --trailer t0 -F "$URL"
```

### 3）按轨道 ID 下载并合并输出
```bash
manzana --no-prompt --trailer t0 -f "v0+a0" "$URL"
manzana --no-prompt --trailer t0 -f "v0+a0+s0" "$URL"
```

---

## 命令速查（常用参数与组合）

- 帮助：
```bash
manzana --help
```

- 列 trailers：
```bash
manzana --list-trailers "$URL"
```

- 列轨道（formats）：
```bash
manzana --no-prompt --trailer t0 -F "$URL"
```

- 选择 trailer：
```bash
manzana --trailer t0 "$URL"
manzana --trailer t1 "$URL"
manzana --trailer all "$URL"
```

- 下载（非交互式）：
```bash
manzana --no-prompt --trailer t0 -f "v0+a0" "$URL"
manzana --no-prompt --trailer t0 -f "v0+a0+s0" "$URL"
```

选择规则：
- 必须且只能包含 1 个 `vN`
- `aN` 可多个：`v0+a0+a3`
- `sN` 可多个：`v0+a0+s0+s1`

- 默认背景视频：
```bash
manzana --default "$URL"
```

- 不要音频 / 不要字幕：
```bash
manzana --no-audio "$URL"
manzana --no-subs "$URL"
```

---

## Linux 自动依赖自举（MP4Box / FFmpeg）

### 这一机制在哪里生效？
无论你是：
- **克隆源码运行**（`python3 manzana.py ...`）
- **安装版运行**（`manzana ...`）

只要进入“下载阶段”（使用了 `-f` 选择轨道、开始下载并合并输出），程序都会执行同一套依赖判断逻辑：
- 必要时确保 MP4Box
- 若选择了字幕轨道，则确保 FFmpeg

> 注意：仅列 trailers / 列 formats（`--list-trailers`、`-F`）不会触发下载依赖包。

### 什么时候需要 FFmpeg？
- 选择了字幕轨道（`sN`）时，需要 FFmpeg 做字幕转换
- 只下载视频+音频（`vN+aN`）通常不需要 FFmpeg

### 自举的下载源（稳定链接）
- MP4Box：`mp4box-bundle-latest`
- FFmpeg（BtbN）：`ffmpeg-bundle-latest`

工具缓存目录默认：
- `~/.cache/manzana/tools`

可自定义：
```bash
export MANZANA_TOOLS_DIR="/path/to/manzana-tools"
```

### 重要：适用范围与限制（务必阅读，避免误解）
自动依赖自举不是在所有系统上都保证可用，它依赖以下条件：

#### ✅ 通常可用的环境（推荐）
- **Linux**
- **x86_64 / amd64**
- 系统 **glibc ≥ 2.35**（当前发布的 MP4Box bundle 基于 Ubuntu 22.04 构建）
- 能正常访问 GitHub Releases 下载文件（网络可达）

#### ⚠️ 可能不可用或需要手动安装的情况
- **非 x86_64**（例如 aarch64/arm64）：当前没有发布对应 bundle
- **glibc 太老**（例如 Ubuntu 20.04 glibc 2.31）：MP4Box bundle 可能无法运行
- **无法访问 GitHub**（内网、被墙、无外网）：bundle 下载会失败
- **你不希望下载大文件**（FFmpeg bundle 体积较大）

如果你处于以上情况，建议改用系统包管理器安装依赖（示例 Debian/Ubuntu）：
```bash
sudo apt-get update
sudo apt-get install -y ffmpeg gpac
```

---

## 输出文件位置说明
- 源码方式（clone 仓库运行）：默认 `./output/`
- 安装版（manzana 命令）：默认 `./video/`（不可写则 `~/video/`）
- 下载开始时会打印“Output file”和“输出路径”（以日志为准）

---

## 排错（Troubleshooting）

### 1）提示 `manzana: command not found`
当前终端执行：
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 2）查看安装日志
安装脚本默认将 pip 输出写入：
- `~/.local/share/manzana/install.log`

查看最后 80 行：
```bash
tail -n 80 ~/.local/share/manzana/install.log
```

### 3）网络波动/Apple 限流
`tv.apple.com` 或 Apple API 可能存在限流/波动，建议重试或更换网络环境。

---

## License
MIT License
