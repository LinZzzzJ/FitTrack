# 开发环境与命令

已发布基线为 v0.4.0；当前 `main` 源码 API 修订号为 5。整理日期：2026-10-24。Windows v0.4.0 流程已有验收。当前源码另在 Linux Python 3.14.4 环境做过有限检查，但**Linux 完整运行、管理功能与跨 OS 迁移仍未验收**；以下候选流程不是支持声明。Linux 开发检查需要系统提供 `venv` / `ensurepip`，隔离依赖安装和测试结果须分别记录。

## 环境与文件的用途

| 项目 | 当前约定 |
|---|---|
| Python | 项目声明 `>=3.10`；源码验收使用 3.12.7，不代表所有更高版本均验收 |
| Node.js | 前端与 CI 使用 24；Linux 需要 Linux 版 Node 和 npm |
| Windows 成品运行时 | 内置 CPython 3.13.16；用户无需另装 Python/Node |
| 前端 | Svelte 5、TypeScript、Vite；版本以 `web/package-lock.json` 为准 |
| Python 开发依赖 | `requirements.lock`，并以 `pip install -e '.[dev]'` 安装本项目 |
| 打包依赖 | `requirements-runtime.lock`、`requirements-build.lock`；用于独立构建环境 |
| 入口 | `python -B -m fittrack`；`pyproject.toml` 也声明 `fittrack` 命令 |
| 前端产物 | `npm --prefix web run build` 输出 `src/fittrack/static`，由 FastAPI 同源提供 |

不要复制 Windows `.venv` 或 `node_modules` 到 Linux 使用。虚拟环境应在目标位置重建，原生模块与工具按平台重新安装。[Python venv 官方说明](https://docs.python.org/3.12/library/venv.html)

## Windows：已验证的流程

在新的固定可写目录克隆，以下命令从仓库根目录运行：

```powershell
git clone https://github.com/LinZzzzJ/FitTrack.git
Set-Location -LiteralPath FitTrack
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

安装脚本创建 `.venv`、安装依赖、构建前端并生成首次设置快捷方式。首次设置选专用根目录，后续快捷方式绑定该目录；这些脚本会写项目依赖和 `artifacts`，不属于只读检查。

已有环境做前台调试时，先创建一个独立空测试目录，使用不同于正式服务的端口：

```powershell
New-Item -ItemType Directory -Force -Path '.\artifacts\dev-root' | Out-Null
$devRoot = (Resolve-Path -LiteralPath '.\artifacts\dev-root').Path
& '.\.venv\Scripts\python.exe' -B -m fittrack --data-root $devRoot --port 8799 --no-browser --no-shortcuts
```

在浏览器手动访问 `http://127.0.0.1:8799`。这里使用构建后的页面，不启动 Vite。关闭前台服务使用 Ctrl+C；不要把测试根目录指向个人正式记录。端口被占用时明确处理冲突，不静默更换实例。

## Linux/WSL：候选流程与当前验证边界

先准备 Linux 原生的 Python（优先 3.12）、venv 支持、Git、Node.js 24 和 npm。具体系统包安装方式取决于发行版，本文不假定默认 Python 版本，也不提供会覆盖现有系统工具的安装脚本。

在已选好的 Linux 开发目录中克隆。使用 Linux 工具开发时，优先将工程放在 Linux 文件系统，而非直接共用 Windows 工作区；这符合 [Microsoft WSL 文件系统建议](https://learn.microsoft.com/en-us/windows/wsl/filesystems)。Windows 和 WSL 可以各有一个克隆，通过 Git 同步源码。

先检查工具归属：

```bash
command -v python3 node npm git
python3 --version
node --version
npm --version
```

`node` 缺失、或 `npm` 解析为 `/mnt/c/...` 的 Windows 安装目录时，先补齐 Linux 工具链，再执行下面命令。2026-10-23 的隔离源码检查使用了 Linux Python 3.14.4 和 Node.js 24；它没有验证 Windows `check.ps1`、Linux 原生管理入口、浏览器全流程或数据迁移。

以下是候选开发步骤，仍须在目标发行版按步骤复验；命令失败时保留错误与版本，不改锁文件“凑通过”：

```bash
git clone https://github.com/LinZzzzJ/FitTrack.git
cd FitTrack
repo_root="$(pwd -P)"
mkdir -p artifacts/linux-dev/tmp artifacts/linux-dev/caches
export PYTHONDONTWRITEBYTECODE=1
export TMPDIR="$repo_root/artifacts/linux-dev/tmp"
export TMP="$TMPDIR" TEMP="$TMPDIR" SQLITE_TMPDIR="$TMPDIR"
export PIP_CACHE_DIR="$repo_root/artifacts/linux-dev/caches/pip"
export npm_config_cache="$repo_root/artifacts/linux-dev/caches/npm"
export RUFF_CACHE_DIR="$repo_root/artifacts/linux-dev/caches/ruff"

python3 -m venv .venv
.venv/bin/python -B -m pip install --no-compile -r requirements.lock
.venv/bin/python -B -m pip install --no-compile -e '.[dev]'
npm --prefix web ci
npm --prefix web run check
npm --prefix web run build
```

进入运行探测前必须先读 [移植清单](migration.md)。显式根目录及关闭桌面入口可绕过部分 Windows 依赖，但不能证明迁移、重启和全部界面能力可用：

```bash
mkdir -p "$repo_root/artifacts/linux-dev/root"
.venv/bin/python -B -m fittrack \
  --data-root "$repo_root/artifacts/linux-dev/root" \
  --port 8799 --no-browser --no-shortcuts
```

成功时在可访问该本机服务的浏览器中手动打开地址；WSL 的代理、网络及浏览器桥接需单独核验。停止前台服务用 Ctrl+C。当前不要用页面整根迁移验证正式数据，相关子进程命令仍有 Windows 路径依赖。

候选检查命令如下。便携版测试含 `winreg`、`ctypes.windll` 等依赖，Linux 预计会遇到平台问题；报告必须区分环境失败、功能失败及待适配测试，不能将删掉/跳过测试记作完整验收：

```bash
.venv/bin/python -B -m pytest \
  --basetemp artifacts/linux-dev/pytest \
  -o cache_dir=artifacts/linux-dev/caches/pytest
.venv/bin/python -B -m ruff check src tests scripts
npm --prefix web run check
npm --prefix web run build
```

## 配置与开发服务器

- 当前生产入口要求显式根目录，使用个人 `CredentialStore`。新账号没有 Key；在设置页配置，AI 测试使用模拟对象。
- `.env.example` 描述旧配置形式；`config.Settings` 保留旧版导入/回归能力。不要在移植时将 `.env` 重新接为所有账号共享 Key。
- `web` 的 Vite 开发服务器代理 `/api` 到 `127.0.0.1:8788`。前后端分离调试时先核对端口、Cookie、Host/Origin 和代理，不能让开发页面误连正式服务。
- 默认业务日期由 `calculations.today` 按固定 UTC+8（上海）计算，当前实现不依赖系统本地时区或额外 tzdata。移植时保持这一口径，不能通过修改机器时钟解锁周资格。
- 运行根目录 `R` 与开发缓存/依赖目录用途不同。进程初始化后 `RuntimePaths.configure_process` 设置临时位置；开发工具的系统安装、浏览器及操作系统自己的文件不属于应用写入边界。

## 当前 CI 与打包

[CI 配置](../.github/workflows/ci.yml) 在 Windows 上运行 Python 3.12、Node 24 和离线检查。它不包含 Linux 矩阵、不自动发布 EXE 或 Release。

Windows 便携版在独立 Windows 环境构建，入口见 `scripts/prepare_release.ps1`、`scripts/build_release.py` 和 `tools/portable.spec`。PyInstaller 包含平台相关运行组件，当前 Windows 包不能当作 Linux 可执行文件使用。[PyInstaller 官方说明](https://pyinstaller.org/en/stable/operating-mode.html)

具体模块与待适配行为见 [架构](ARCHITECTURE.md)、[跨平台移植](migration.md)。
