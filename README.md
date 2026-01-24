<!-- README.md @ v1.9.1
更新说明：
- 全中文 + 用词规范：交互式（Interactive）/非交互式（Non-interactive）
- 三种入口分区清晰：Actions / 源码（git clone）/ 一键安装（manzana）
- 所有示例命令均为“整块可复制”，避免用户只复制半行导致误解
- 同一功能点同时提供两种风格：
  A) 变量写法（适合连续多条命令）
  B) 单行直写 URL（适合习惯一行命令的用户）
- 删除 “python3 manzana.py ...” 这类占位写法，改为明确可执行命令
- 新增“高级/排障环境变量与开关”章节，集中列清楚可用变量及使用场景
-->

# Manzana（Apple TV+ 预告片下载器）

Manzana 用于下载 Apple TV+ 页面中的预告片/花絮/片段（Trailers/Clips/Teaser）。  
支持列出可用的视频/音频/字幕轨道，并按你的选择下载分片、合并输出 MP4 文件（并写入基本元数据/封面）。

---

## 术语与模式（先读）
- **交互式（Interactive）**：程序会提示并等待输入（选择 trailer、选择轨道 ID 等），适合手动操作。
- **非交互式（Non-interactive）**：程序不提示、不等待输入；参数一次性给全，适合脚本/CI。常用 `--no-prompt` 与 `-F / -f`。

---

## 三种使用入口（选一种即可）

### 入口 A：GitHub Actions（网页运行）
适合不想本地配置环境的用户。  
在仓库页面打开 **Actions** → 运行 `Manzana Download (Apple TV+ Trailers)`，按表单填写 URL、trailer、preset/custom 等参数即可。

> 注意：Actions workflow 中的 ffmpeg/mp4box 安装与缓存逻辑已优化，建议保持现状，不要随意改动。

---

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

#### B3）确认可运行
```bash
python3 manzana.py --help
```

---

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

---

## 输出目录在哪里？
- **Actions**：workflow 工作目录下的 `output/`（并上传 artifact）
- **源码方式（git clone）**：仓库目录下 `./output/`
- **安装版（manzana 命令）**：当前目录 `./video/`（不可写则 `~/video/`）

---

# 交互式（Interactive）用法（独立说明）
> 交互式只要满足：**不加 `--no-prompt` 且在真实 TTY 终端**。  
> 适用于：源码方式（python3 manzana.py）和安装版（manzana）。

示例 URL：
- 你可以用变量写法（更适合重复使用）：
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

## I-1）最简单：交互式全流程
### 源码方式（交互式）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
python3 manzana.py "$URL"
```

### 安装版（交互式）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana "$URL"
```

你将被依次提示输入（示例）：
1) trailer 选择（t0/t1/... 或 all）  
2) 视频轨道 ID（必须选一个）  
3) 音频轨道 ID（可选多个或 all）  
4) 字幕轨道 ID（可选多个或 all）

## I-2）交互式下快速跳过音频/字幕选择
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

## I-3）交互式下载默认背景视频（只取默认）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --default "$URL"
```

---

# 非交互式（Non-interactive）用法（独立说明）
> 非交互式推荐固定流程：  
> **先列 trailers → 再列 formats(-F) → 再用 -f 精确下载**  
> 适用于脚本/CI，或你想完全可复现。

## N-0）准备 URL（两种写法二选一）
### A) 变量写法（适合连续多条命令）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

### B) 单行直写 URL（适合只跑一条命令）
你可以直接把 URL 写在命令里，例如：
```bash
manzana --list-trailers "https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

> 提示：`URL="..."` 不是注释，它是“设置变量”的命令；如果你用变量写法，需要连同后续命令一起执行。

---

## N-1）列出该页面有哪些视频（t0/t1/t2...）
### 变量写法
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --list-trailers "$URL"
```

### 单行写法
```bash
manzana --list-trailers "https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

---

## N-2）列出轨道（formats），获取 vN/aN/sN
### 变量写法
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -F "$URL"
```

### 单行写法
```bash
manzana --no-prompt --trailer t0 -F "https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

---

## N-3）按轨道下载（最常用示例）
### 规则（非常重要）
- `-f/--format` 必须且只能包含 **一个** 视频轨：`vN`
- 可包含多个音频轨：`aN+aM+...`
- 可包含多个字幕轨：`sN+sM+...`

### 示例 1：视频+音频
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0+a0" "$URL"
```

### 示例 2：视频+音频+字幕
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0+a0+s0" "$URL"
```

### 示例 3：纯视频（不带音频/字幕）
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0" "$URL"
```

### 示例 4：多个音频/多个字幕
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer t0 -f "v0+a0+a3+s0+s2" "$URL"
```

---

## N-4）`--trailer all` 在非交互式下如何用？
你可以这样做（对每个 trailer 使用同一个 `-f`）：

```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
manzana --no-prompt --trailer all -f "v0+a0" "$URL"
```

⚠️ 风险说明（务必理解）：
- 不同 trailer 的轨道编号/可用轨道可能不一致  
- 如果某个 trailer 没有你指定的 `a0` 或 `s0`，程序会报错退出  
- 更稳妥做法：分别对 t0/t1/t2 单独跑，或使用 Actions preset（每个视频单独计算 format）

---

## 参数有效性与互斥规则（必读）
为避免误用，这里写清“什么时候有效、什么时候无效”：

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

---

## Linux 自动依赖自举（MP4Box / FFmpeg）
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

---

## 高级 / 排障环境变量与开关（Advanced）
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

---

## 排错（Troubleshooting）
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

---

## License
MIT License
