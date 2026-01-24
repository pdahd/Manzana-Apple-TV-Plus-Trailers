<!-- README.md @ v1.9.0
更新说明：
- 更全面、结构更清晰：三种入口 + 两种模式（交互式/非交互式）严格分区
- 明确参数“何时有效/何时无效/何时互斥”
- 为每种用法提供多条可复制示例命令，避免用户自行猜测逻辑
-->

# Manzana（Apple TV+ 预告片下载器）

Manzana 用于下载 Apple TV+ 页面中的预告片/花絮/片段（Trailers/Clips/Teaser）。  
支持列出视频/音频/字幕轨道，按选择下载分片、合并输出 MP4 文件，并写入基本元数据（标题/年份/封面等）。

---

## 目录（建议先按入口选，再按模式用）
- [术语与模式](#术语与模式)
- [三种入口（选一种即可）](#三种入口选一种即可)
  - [入口 A：GitHub Actions](#入口-a-github-actions)
  - [入口 B：克隆仓库本地运行（源码）](#入口-b-克隆仓库本地运行源码)
  - [入口 C：一键安装（manzana 命令）](#入口-c-一键安装manzana-命令)
- [输出目录在哪里？](#输出目录在哪里)
- [交互式（Interactive）用法（独立说明）](#交互式interactive用法独立说明)
- [非交互式（Non-interactive）用法（独立说明）](#非交互式non-interactive用法独立说明)
- [参数有效性与互斥规则（必读）](#参数有效性与互斥规则必读)
- [Linux 自动依赖自举（MP4Box/FFmpeg）](#linux-自动依赖自举mp4boxffmpeg)
- [排错（Troubleshooting）](#排错troubleshooting)
- [License](#license)

---

## 术语与模式
- **交互式（Interactive）**：程序会在终端里提示并等待输入（选择 trailer、选择轨道 ID 等）。适合人工操作。
- **非交互式（Non-interactive）**：程序不提示、不等待输入；参数一次性给全。适合脚本/CI。通常配合 `--no-prompt` 与 `-F / -f` 使用。

---

## 三种入口（选一种即可）

### 入口 A：GitHub Actions
适合不想本地配置环境的用户。

在仓库页面打开 **Actions** → 运行 `Manzana Download (Apple TV+ Trailers)`：
- 输入 URL、trailer（t0/t1/... 或 all）、preset/custom 等参数
- 运行结束后会在 Artifacts 中提供输出 MP4

> 注意：Actions workflow 中的 ffmpeg/mp4box 安装与缓存逻辑已优化，建议保持现状。

---

### 入口 B：克隆仓库本地运行（源码）
适合想直接运行源码或二次开发的用户。

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

#### B3）运行（交互式 / 非交互式）
你可以用：
- `python3 manzana.py ...`

---

### 入口 C：一键安装（manzana 命令）
适合在 Linux 虚拟机/服务器/容器中快速使用，不需要 sudo。

**一条命令安装并立即可用：**
```bash
export PATH="$HOME/.local/bin:$PATH"; curl -fsSL https://raw.githubusercontent.com/pdahd/Manzana-Apple-TV-Plus-Trailers/main/install-manzana.sh | bash
```

安装完成后：
```bash
manzana --help
```

---

## 输出目录在哪里？
输出目录取决于你使用的入口：

- **入口 B（源码方式）**：默认输出到仓库目录下 `./output/`
- **入口 C（安装版 manzana）**：默认输出到当前目录 `./video/`
  - 若当前目录不可写，则回退到 `~/video/`
  - 下载开始时会打印完整输出路径（以日志中的 `输出路径:` 为准）
- **入口 A（Actions）**：输出到 workflow 工作目录中的 `output/` 并上传 artifact（不建议改）

---

# 交互式（Interactive）用法（独立说明）
> 交互式只要满足：**不加 `--no-prompt` 且在真实 TTY 终端**。  
> 推荐入口：源码方式或安装版都可以。

示例 URL：
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

## I-1）最简单：交互式全流程（会提示多次输入）
- 源码方式：
```bash
python3 manzana.py "$URL"
```

- 安装版：
```bash
manzana "$URL"
```

你将被依次提示输入：
1) trailer 选择（t0/t1/... 或 all）  
2) 视频轨道 ID（必须选一个）  
3) 音频轨道 ID（可选多个或 all）  
4) 字幕轨道 ID（可选多个或 all）

## I-2）交互式下跳过音频/字幕选择（快速）
- 跳过音频（仅下载视频 + 可选字幕）：
```bash
manzana --no-audio "$URL"
```

- 跳过字幕（仅下载视频+音频）：
```bash
manzana --no-subs "$URL"
```

> 注意：这两个参数在交互式下最有价值（减少选择步骤）。

## I-3）交互式下载默认背景视频（只取默认）
```bash
manzana --default "$URL"
```

---

# 非交互式（Non-interactive）用法（独立说明）
> 非交互式建议按固定流程：  
> **先列 trailers → 再列 formats(-F) → 再用 -f 精确下载**  
> 推荐用于脚本/CI，或你想完全可复现。

示例 URL：
```bash
URL="https://tv.apple.com/us/movie/f1-the-movie/umc.cmc.3t6dvnnr87zwd4wmvpdx5came?ctx_agid=502c9996"
```

## N-1）列出该页面有哪些视频（t0/t1/t2...）
```bash
manzana --list-trailers "$URL"
```

## N-2）列出轨道（formats），获取 vN/aN/sN
```bash
manzana --no-prompt --trailer t0 -F "$URL"
```

## N-3）按轨道下载（最常用示例）
- 视频+音频：
```bash
manzana --no-prompt --trailer t0 -f "v0+a0" "$URL"
```

- 视频+音频+字幕：
```bash
manzana --no-prompt --trailer t0 -f "v0+a0+s0" "$URL"
```

- 纯视频（不带音频/字幕）：
```bash
manzana --no-prompt --trailer t0 -f "v0" "$URL"
```

### `-f/--format` 的组合规则（非常重要）
- 必须且只能包含 **一个** 视频轨：`vN`
- 可包含多个音频轨：`aN+aM+...`
- 可包含多个字幕轨：`sN+sM+...`

示例：
```bash
manzana --no-prompt --trailer t0 -f "v0+a0+a3+s0+s2" "$URL"
```

## N-4）`--trailer all` 在非交互式下如何用？
你可以这样做（会对每个 trailer 使用同一个 `-f`）：

```bash
manzana --no-prompt --trailer all -f "v0+a0" "$URL"
```

但务必理解风险：

- 不同 trailer 的轨道编号/可用轨道可能不同  
- 如果某个 trailer 不存在你指定的 `a0` 或 `s0`，程序会报错退出  
- 更稳妥做法：分别对 t0/t1/t2 单独跑，或使用 Actions preset（每个视频单独计算 format）

---

## 参数有效性与互斥规则（必读）
为了避免“买彩票式乱组合”，这里把规则写死：

### 1）`--no-audio` / `--no-subs`
- **交互式有效**（用于跳过选择步骤）
- **非交互式不推荐使用**：因为非交互式应由 `-f` 控制轨道
- 当你提供 `-f` 时，程序会提示并忽略 `--no-audio/--no-subs`（以 `-f` 为准）

### 2）`--no-prompt`
- 表示“非交互式/不允许提示输入”
- 在非交互式下：
  - `-F`（列 formats）可以不下载
  - 真正下载必须给 `-f`（否则会退出并提示你先 -F 再 -f）

### 3）`--default`
- 表示只取默认背景视频（页面通常只有一个默认视频）
- 与 `--trailer all` 同时使用时，通常没有实际意义（默认视频本身就是一个）

---

## Linux 自动依赖自举（MP4Box/FFmpeg）
### 何时会触发？
- 仅在“下载阶段”（使用 `-f` 并开始下载与合并）才会检查工具
- 列 trailers / 列 formats（`--list-trailers`、`-F`）不会触发工具下载

### 工具需求规则
- MP4Box：合并输出 mp4 必需（几乎每次下载都需要）
- FFmpeg：**仅当你选择了字幕轨道（sN）** 时需要（用于字幕转换）

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
自动依赖自举依赖以下条件：

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

## 排错（Troubleshooting）
### 1）安装后提示 `manzana: command not found`
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 2）查看安装日志
```bash
tail -n 80 ~/.local/share/manzana/install.log
```

### 3）网络问题/限流
tv.apple.com 可能波动或限流，建议重试或更换网络环境。

---

## License
MIT License
