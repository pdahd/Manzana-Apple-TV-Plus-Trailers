<!-- README.md @ v1.9.2
更新说明：
- 增加“清晰且稳定”的目录（TOC），使用显式锚点避免 GitHub 自动锚点在中文标题下不稳定的问题
- 保持 v1.9.1 的结构：三种入口 + 交互式/非交互式严格分区 + 全部示例均为“整块可复制”
- 不遗漏：自动依赖自举适用范围/限制、参数有效性与互斥、安装脚本参数与变量、排障等
-->

<a id="top"></a>

# Manzana（Apple TV+ 预告片下载器）

Manzana 用于下载 Apple TV+ 页面中的预告片/花絮/片段（Trailers/Clips/Teaser）。  
支持列出可用的视频/音频/字幕轨道，并按你的选择下载分片、合并输出 MP4 文件（并写入基本元数据/封面）。

---

<a id="toc"></a>

## 目录（Table of Contents）

1. [术语与模式](#terms)
2. [三种使用入口（选一种即可）](#entrypoints)
   - [入口 A：GitHub Actions（网页运行）](#entry-actions)
   - [入口 B：克隆仓库本地运行（源码方式）](#entry-clone)
   - [入口 C：一键安装（manzana 命令）](#entry-install)
3. [输出目录在哪里？](#output-dir)
4. [交互式（Interactive）用法（独立说明）](#interactive)
5. [非交互式（Non-interactive）用法（独立说明）](#noninteractive)
6. [参数有效性与互斥规则（必读）](#rules)
7. [Linux 自动依赖自举（MP4Box / FFmpeg）](#bootstrap)
8. [高级 / 排障环境变量与开关（Advanced）](#advanced)
9. [排错（Troubleshooting）](#troubleshooting)
10. [License](#license)

---

<a id="terms"></a>

## 1) 术语与模式

- **交互式（Interactive）**：程序会提示并等待输入（选择 trailer、选择轨道 ID 等），适合手动操作。
- **非交互式（Non-interactive）**：程序不提示、不等待输入；参数一次性给全，适合脚本/CI。常用 `--no-prompt` 与 `-F / -f`。

---

<a id="entrypoints"></a>

## 2) 三种使用入口（选一种即可）

<a id="entry-actions"></a>

### 入口 A：GitHub Actions（网页运行）
适合不想本地配置环境的用户。  
在仓库页面打开 **Actions** → 运行 `Manzana Download (Apple TV+ Trailers)`，按表单填写 URL、trailer、preset/custom 等参数即可。

> 注意：Actions workflow 中的 ffmpeg/mp4box 安装与缓存逻辑已优化，建议保持现状，不要随意改动。

[返回目录](#toc)

---

<a id="entry-clone"></a>

### 入口 B：克隆仓库本地运行（源码方式，兼容原作者用法）
适合想直接运行源码或二次开发的用户。  
输出目录（源码方式）：默认 `./output/`

#### B1）准备环境（Debian/Ubuntu 示例）
```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-pip
```

#### B2）克隆 + 安装 Python 依赖
```bash
git clone https://github.com/pdahd/Manzana-Apple-TV-Plus-Trailers.git
cd Manzana-Apple-TV-Plus-Trailers

python3 -m pip install --upgrade pip
pip3 install -r requirements.txt
```

#### B3）确认可运行（不会下载视频）
```bash
python3 manzana.py --help
```

> 说明：真正下载必须提供 URL（以及非交互式情况下必须提供 `-f`），仅运行 `python3 manzana.py` 不会自动开始下载。

[返回目录](#toc)

---

<a id="entry-install"></a>

### 入口 C：一键安装（推荐：安装后直接使用 `manzana` 命令）
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
- 下载开始时会打印完整输出路径（以日志中的 `输出路径:` 为准）

[返回目录](#toc)

---

<a id="output-dir"></a>

## 3) 输出目录在哪里？

- **Actions**：workflow 工作目录下的 `output/`（并上传 artifact）
- **源码方式（git clone）**：仓库目录下 `./output/`
- **安装版（manzana 命令）**：当前目录 `./video/`（不可写则 `~/video/`）

[返回目录](#toc)

---

<a id="interactive"></a>

## 4) 交互式（Interactive）用法（独立说明）

> 交互式只要满足：**不加 `--no-prompt` 且在真实 TTY 终端**。  
> 适用于：源码方式（python3 manzana.py）和安装版（manzana）。

### I-1）交互式全流程（最常用）
#### 源码方式（交互式）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
python3 manzana.py "$URL"
```

#### 安装版（交互式）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana "$URL"
```

你将被依次提示输入（示例）：
1) trailer 选择（t0/t1/... 或 all）  
2) 视频轨道 ID（必须选一个）  
3) 音频轨道 ID（可选多个或 all）  
4) 字幕轨道 ID（可选多个或 all）

### I-2）交互式下快速跳过音频/字幕选择
> `--no-audio/--no-subs` 在交互式下最有用（减少交互步骤）。

- 跳过音频（仅下载视频 + 可选字幕）：
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-audio "$URL"
```

- 跳过字幕（仅下载视频+音频）：
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-subs "$URL"
```

### I-3）交互式下载默认背景视频（只取默认）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --default "$URL"
```

[返回目录](#toc)

---

<a id="noninteractive"></a>

## 5) 非交互式（Non-interactive）用法（独立说明）

> 非交互式推荐固定流程：  
> **先列 trailers → 再列 formats(-F) → 再用 -f 精确下载**  
> 适用于脚本/CI，或你想完全可复现。

### N-1）列出该页面有哪些视频（t0/t1/t2...）
#### 变量写法
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --list-trailers "$URL"
```

#### 单行直写 URL
```bash
manzana --list-trailers "https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

### N-2）列出轨道（formats），获取 vN/aN/sN
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -F "$URL"
```

### N-3）按轨道下载（最常用示例）
#### 规则（非常重要）
- `-f/--format` 必须且只能包含 **一个** 视频轨：`vN`
- 可包含多个音频轨：`aN+aM+...`
- 可包含多个字幕轨：`sN+sM+...`

示例 1：视频+音频
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0+a0" "$URL"
```

示例 2：视频+音频+字幕
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0+a0+s0" "$URL"
```

示例 3：纯视频（不带音频/字幕）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0" "$URL"
```

示例 4：多个音频/多个字幕
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0+a0+a3+s0+s2" "$URL"
```

### N-4）`--trailer all` 在非交互式下如何用？
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer all -f "v0+a0" "$URL"
```

⚠️ 风险说明（务必理解）：
- 不同 trailer 的轨道编号/可用轨道可能不一致  
- 如果某个 trailer 没有你指定的 `a0` 或 `s0`，程序会报错退出  
- 更稳妥做法：分别对 t0/t1/t2 单独跑，或使用 Actions preset（每个视频单独计算 format）

[返回目录](#toc)

---

<a id="rules"></a>

## 6) 参数有效性与互斥规则（必读）

### 1）`--no-audio` / `--no-subs`
- **交互式有效**：用于跳过音频/字幕选择步骤
- **非交互式不推荐**：非交互式应由 `-f` 控制是否包含 aN/sN
- 当你提供 `-f` 时，程序会提示并忽略 `--no-audio/--no-subs`（以 `-f` 为准）

### 2）`--no-prompt`
- 表示“非交互式/不允许提示输入”
- 非交互式下载必须提供 `-f`（否则会退出并提示你先 -F 再 -f）

### 3）`--default`
- 表示只取默认背景视频（页面通常只有一个默认视频）
- 与 `--trailer all` 同时使用通常没有意义（默认视频本身就是单个）

[返回目录](#toc)

---

<a id="bootstrap"></a>

## 7) Linux 自动依赖自举（MP4Box / FFmpeg）

### 何时会触发？
- 仅在“下载阶段”（使用 `-f` 并开始下载与合并）才会检查工具
- 列 trailers / 列 formats（`--list-trailers`、`-F`）不会触发工具下载

### 工具需求规则
- MP4Box：合并输出 mp4 必需（几乎每次下载都需要）
- FFmpeg：仅当选择字幕轨道（sN）时需要（用于字幕转换）

### 下载源（稳定链接）
- MP4Box：`mp4box-bundle-latest`
- FFmpeg（BtbN）：`ffmpeg-bundle-latest`

### 缓存目录
默认：
- `~/.cache/manzana/tools`

可自定义：
```bash
export MANZANA_TOOLS_DIR="/path/to/manzana-tools"
```

### 适用范围与限制（避免误解）
✅ 通常可用：
- Linux
- x86_64/amd64
- glibc ≥ 2.35（当前 MP4Box bundle 基于 Ubuntu 22.04 构建）
- 能访问 GitHub Releases 下载

⚠️ 可能不可用/需手动安装：
- 非 x86_64（例如 arm64/aarch64）
- glibc 太老（例如 Ubuntu 20.04）
- 无法访问 GitHub
- 不希望下载大文件（ffmpeg bundle 较大）

手动安装系统依赖（Debian/Ubuntu）：
```bash
sudo apt-get update
sudo apt-get install -y ffmpeg gpac
```

[返回目录](#toc)

---

<a id="advanced"></a>

## 8) 高级 / 排障环境变量与开关（Advanced）
> 仅在需要排障或特殊环境时使用。普通用户可以忽略。

### 1）工具缓存目录
```bash
export MANZANA_TOOLS_DIR="/path/to/manzana-tools"
```

### 2）自定义 bundle 下载源（镜像/内网）
```bash
export MANZANA_MP4BOX_BUNDLE_BASE="https://github.com/<owner>/<repo>/releases/download/mp4box-bundle-latest"
export MANZANA_FFMPEG_BUNDLE_BASE="https://github.com/<owner>/<repo>/releases/download/ffmpeg-bundle-latest"
```

### 3）强制使用 bundle（仅排障）
这些开关是 **debug-gated**：必须先 `MANZANA_DEBUG=1` 才会生效，避免误触导致每次都下载大包。

```bash
export MANZANA_DEBUG=1
export MANZANA_FORCE_BUNDLE_MP4BOX=1
export MANZANA_FORCE_BUNDLE_FFMPEG=1
```

### 4）安装脚本相关（可选）
- 安装指定版本（tag/branch/commit）：
```bash
export PATH="$HOME/.local/bin:$PATH"; MANZANA_REF="main" curl -fsSL https://raw.githubusercontent.com/pdahd/Manzana-Apple-TV-Plus-Trailers/main/install-manzana.sh | bash
```

- 显示 pip 全量输出（排障用）：
```bash
export PATH="$HOME/.local/bin:$PATH"; MANZANA_INSTALL_VERBOSE=1 curl -fsSL https://raw.githubusercontent.com/pdahd/Manzana-Apple-TV-Plus-Trailers/main/install-manzana.sh | bash
```

[返回目录](#toc)

---

<a id="troubleshooting"></a>

## 9) 排错（Troubleshooting）

### 1）安装后提示 `manzana: command not found`
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 2）查看安装日志（pip 输出默认写入 log）
```bash
tail -n 80 ~/.local/share/manzana/install.log
```

### 3）网络问题/限流
tv.apple.com 可能波动或限流，建议重试或更换网络环境。

[返回目录](#toc)

---

<a id="license"></a>

## 10) License
MIT License
