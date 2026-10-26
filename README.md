# MdNote

> MdNote 是一款支持即时排版与源码编辑的 Markdown 桌面编辑器，基于 **Python + PySide6** 构建。
> 默认显示排版结果、点击即可编辑，也可一键切换到整篇源码模式。
> 设计目标：**流畅、轻量、可扩展、安全**，长文档低负载。

---

## 📖 项目介绍

MdNote 把「写作」与「排版」合二为一，提供两种由你掌控的全局模式：

- **渲染后模式（默认）**：整篇文档直接显示排版结果。点击任意位置，
  即可输入；在段落末尾按回车后显示已完成内容的排版并继续编辑新行，
  点到别处或按 `Esc` 也可恢复排版。输入内容同步到文档，保存无需先点击编辑区外。
- **源码模式**：按 `Ctrl+/` 整体切换到整篇 Markdown 原文，
  带行号区与语法高亮；再按一次切回排版。

两种模式共用同一份文档内容，切换不丢内容，也不存在系统自动来回跳转的混乱。
应用以原生 Python / Qt 构建，排版由独立的 WebEngine 进程承担。

## ✨ 功能一览

### 编辑体验

- **多标签**：同时打开多个文件，`Ctrl+T` 新建标签、`Ctrl+W` 关闭标签、
  `Ctrl+Tab` / `Ctrl+Shift+Tab` 切换标签；同一文件不会重复打开
- 双模式（每个标签独立）：渲染后所见即所得 / 整篇源码，`Ctrl+/` 切换
- 点击任意位置光标精确就位；中文输入法组字期间不被打断
- **命令面板**（`Ctrl+Shift+P`）：搜索并执行任意菜单命令，附快捷键提示
- **常用格式快捷键**（两种模式通用）：加粗 `Ctrl+B`、斜体 `Ctrl+I`、
  删除线 `Ctrl+Shift+X`、行内代码 `Ctrl+Shift+\``、链接 `Ctrl+K`
- 一键插入代码块（`Ctrl+Shift+K`）、表格、分隔线、图片（`Ctrl+Shift+I`）、任务项（`Ctrl+Shift+Enter`）
- 智能回车（见下）、行首退格合并、`Tab` 缩进
- 符号自动配对，可选智能弯引号
- **全键盘可操作**：`F6` 在编辑器 / 侧边栏 / 查找栏间循环焦点；
  侧边栏 `Esc` 返回编辑器

### 智能回车

> 无论在块的什么位置按 Enter，都**在光标处截断、后半段移到下一行**：
>
> - **列表**：自动续一行同级标记，有序列表自动递增；在空标记上再回车则取消格式
> - **引用**：自动续 `>` 前缀，空引用再回车退出
> - **标题**：标题中间回车，后半段成为普通段落
> - 其他位置：在光标处换行

### Markdown 语法

- 标题、加粗 / 斜体 / 删除线、行内代码、引用、分隔线、内嵌 HTML
- 有序 / 无序 / 任务列表、链接、图片
- 空格快捷输入：`# `、`- `、`> `、`1. `、`- [ ] `、` ``` `、`~~`
- **代码块**：正文直接编辑且隐藏围栏，语言选择、Pygments 离线高亮、行号开关、一键复制；
  输入三个反引号即可显示语言建议，支持 130 项语言 / 格式预设、别名搜索及方向键选择；语言框点击可展开完整列表。
  C/C++、Python、JavaScript 等语言提供自动缩进与括号补全，多行缩进保留原生撤销
- **数学公式**：KaTeX 渲染行内 `$...$` 与块级 `$$...$$`
- **Mermaid 图表**：流程图、UML 类图 / 时序图、架构图、甘特图、饼图等；
  点击图表编辑源码并实时预览，点击外部或按 `Esc` / `Ctrl+Enter` 恢复图表，无需切换整篇源码模式。
  PlantUML、Graphviz / DOT、D2 等也提供语言预设，当前保留为源码展示。
- **可视化表格**：单元格直接编辑、Tab 跨格导航、末格 Tab 新增行；
  Ctrl+Enter 在下方新增行、Alt+Enter 在右侧新增列，光标跟随且保留列对齐；
  菜单可在下方插入行 / 右侧插入列、删除行列、设置列对齐
- **`[toc]` 自动目录**：随文档更新，点击跳转
- **YAML Front Matter**：头部元信息解析展示
- **自定义扩展**：可在设置中启停 Python-Markdown 插件（见[扩展开发](docs/plugin-development.md)）

> KaTeX、Mermaid 等资源**已离线内置**，无需联网即可使用。

### 沉浸式写作

- **超长文档按需排版**：文档很大时只渲染视口附近的块，远离视口的块以等高占位代替，滚动时动态挂载 / 卸载，DOM 规模与文档长度解耦
- **七套内置主题**（渲染与源码模式同步生效，设置中切换即时预览）：
  浅色、深色、护眼（Solarized）、羊皮纸、深夜（OLED）、Monokai、Dracula
- **专注模式**（`F8`）：仅当前块高亮，其余变暗
- **打字机模式**（`F9`）：光标保持在屏幕中部
- 侧边栏：文件树（双击打开）+ 大纲（点击跳转、当前章节高亮）
  + **搜索**（`Ctrl+Shift+F`）：在已打开的文件夹中按文件名与正文检索，
    点击结果可打开文件并定位到具体行；后台线程执行，不阻塞界面
- 状态栏：保存状态、字数 / 字符 / 行数、阅读时长、当前模式

### 文件、图片、导出与更新

- 新建 / 打开 / 保存 / 另存为 / 打开文件夹
- 自动保存（可开关）、会话与最近文件恢复
- 图片**拖拽 / 粘贴自动落盘**（可配置图片目录与相对 / 绝对路径）
- 外部程序修改当前文件时提示重新载入
- 导出 **HTML / PDF / PNG / JPEG**
- 安装 **Pandoc** 后可导出 **Word (.docx) / ePub / LaTeX / ODT**
- **自动更新**：启动后自动检查更新清单（可在设置中关闭），发现新版本经
  **SHA256 校验**后下载安装；帮助菜单可手动「检查更新…」，清单地址可自定义

## 🚀 快速开始

### 环境要求

- **Python ≥ 3.10**（推荐 3.11 / 3.12），含 pip
- Windows 10+（也可在 macOS / Linux 运行；打包主要在 Windows 验证）

### 从源码运行

```bash
# 获取代码并进入目录
cd md_tool

# （可选）创建虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate        # macOS / Linux

# 安装依赖
pip install -r requirements.txt

# 启动
python -m mdnote
```

启动后窗口自动打开；若上次有打开的文件会自动恢复，否则显示欢迎文档。

### 运行测试

```bash
# Python：单元测试 + WebEngine 集成测试（驱动真实页面交互）
python -m unittest discover -s tests -p "test_*.py"

# JavaScript：编辑器页面用例（Node 内置测试器，需 Node 18+）
node --test tests/test_html_to_md.js tests/test_code_editing.js tests/test_md_inline.js
```

在无显示环境（CI、远程会话）中先切到离屏平台：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu"
```

测试写入临时目录，不操作用户文档；覆盖范围与最近一次结果见[测试文档](docs/testing.md)。

## 📦 构建与安装

生成安装包共三步，**顺序不能颠倒**：先打包应用目录，再生成文件清单，最后编译安装程序。

### 1. 打包应用目录

```bash
pip install pyinstaller
pyinstaller mdnote.spec --noconfirm
```

产物位于 `dist/MdNote/`，先运行其中的 `MdNote.exe` 确认打包结果可用。
`build/`、`dist/` 均为构建产物，已被 Git 忽略。

### 2. 生成安装文件清单

```bash
python scripts/prepare_installer.py
```

脚本遍历 `dist/MdNote/`，读取 `mdnote/__init__.py` 的 `__version__`，生成
`installer/generated-files.nsh`：安装与卸载的文件清单，以及安装包使用的版本号。

- 该文件是**生成产物且已被 Git 忽略，克隆仓库后并不存在**，必须先生成再编译。
- 每次重新打包应用后都要重跑，否则安装包内的文件清单与 `dist/MdNote/` 不一致。
- 需要指定别的目录或输出文件时用
  `python scripts/prepare_installer.py --dist <目录> --out <文件>`。

### 3. 编译安装程序

需要 [NSIS](https://nsis.sourceforge.io/Download) 3.0 或更高版本，并确保 `makensis`
在 `PATH` 上（`makensis -VERSION` 可确认）：

```bash
makensis installer/setup.nsi
```

产物是仓库根目录下的 `MdNote-Setup-<版本号>.exe`（例如 `MdNote-Setup-0.2.0.exe`）。
**安装时可自定义安装路径**，并创建开始菜单快捷方式、注册卸载程序；卸载只删除
应用自身的文件，保留用户创建的文档与资源。

> 安装包体积主要来自 Qt WebEngine（Chromium 内核）运行时，
> 这是高质量 HTML/CSS 排版所必需的部分；应用自身代码占比很小。

静默安装可用于验证安装包（需要管理员权限；`/D` 必须是最后一个参数且不加引号，
目标须为空目录或已有 MdNote 安装）：

```powershell
.\MdNote-Setup-0.2.0.exe /S /D=D:\tmp\MdNote-test
D:\tmp\MdNote-test\Uninstall.exe /S
```

#### 编译报错对照

| 报错 | 原因与处理 |
| --- | --- |
| `!include: could not find: "generated-files.nsh"` | 跳过了第 2 步。该文件是生成产物，克隆后不存在，先运行 `python scripts/prepare_installer.py` |
| `Missing installer/generated-files.nsh. Run from the project root: ...` | 同上；`installer/setup.nsi` 在编译一开始就检查该文件，并提示这条信息 |
| `Build directory must contain MdNote.exe` | `dist/MdNote/` 尚未打包或不完整，先完成第 1 步 |
| `Can't open script "installer/setup.nsi"` | 当前目录不是仓库根目录；在根目录执行，或改用脚本的完整路径 |
| `!include: could not find: "MUI2.nsh"` 等 NSIS 自带头文件 | `makensis` 来自不完整的 NSIS 安装，或版本低于 3.0（脚本用到 3.x 的预处理指令） |

### 发布更新（可选）

发布新版本时用安装包生成更新清单，上传后其 raw 地址即应用中的「更新清单 URL」：

```bash
python scripts/make_manifest.py --installer MdNote-Setup-0.2.0.exe \
    --url https://gitee.com/<用户>/<仓库>/releases/download/v0.2.0/MdNote-Setup-0.2.0.exe \
    --notes-file notes.md --out latest.json
```

脚本计算安装包 SHA256 并写入清单；`--version` 默认取 `mdnote/__init__.py` 的
`__version__`，与之不符会直接报错。应用内置的清单地址在 `mdnote/config.py` 的
`DEFAULT_MANIFEST_URL`，用户也可在设置里改用其它地址。

### 可选：Pandoc

- Windows：`winget install --id JohnMacFarlane.Pandoc`
- 或访问 <https://pandoc.org/installing.html>
- 安装后重启应用，导出菜单中的 docx / epub / LaTeX / ODT 即可用

## ⌨️ 快捷键

| 功能 | 快捷键 |
| --- | --- |
| 新建（重置当前标签） / 打开 / 保存 | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` |
| 新建标签 / 关闭标签 | `Ctrl+T` / `Ctrl+W` |
| 下一 / 上一标签 | `Ctrl+Tab` / `Ctrl+Shift+Tab` |
| 打开文件夹 / 另存为 | `Ctrl+Shift+O` / `Ctrl+Shift+S` |
| 撤销 / 重做 | `Ctrl+Z` / `Ctrl+Y` |
| 加粗 / 斜体 / 删除线 | `Ctrl+B` / `Ctrl+I` / `Ctrl+Shift+X` |
| 行内代码 / 链接 | `Ctrl+Shift+\`` / `Ctrl+K` |
| 表格新增行 / 新增列（光标在单元格内） | Ctrl+Enter / Alt+Enter |
| 代码缩进 / 取消缩进 / 返回正文 | Tab / Shift+Tab / Ctrl+Enter |
| 插入代码块 / 表格 / 分隔线 / 图片 | `Ctrl+Shift+K` / 菜单 / 菜单 / `Ctrl+Shift+I` |
| 切换任务项 / 编辑当前块源码 | `Ctrl+Shift+Enter` / `F2` |
| 查找 / 替换 / 全选 | `Ctrl+F` / `Ctrl+H` / `Ctrl+Shift+A` |
| 查找下一个 / 上一个 | `F3` / `Shift+F3` |
| 切换源码 / 渲染后模式 | `Ctrl+/` |
| 命令面板 | `Ctrl+Shift+P` |
| 侧边栏：切换 / 文件树 / 大纲 / 文件夹搜索 / 返回编辑器 | `Ctrl+J` / `Ctrl+Shift+E` / `Ctrl+Shift+L` / `Ctrl+Shift+F` / `Ctrl+Alt+E` |
| 下一 / 上一区域焦点 | `F6` / `Shift+F6` |
| 专注模式 / 打字机模式 | `F8` / `F9` |
| 设置 | `Ctrl+,` |
| 退出 | `Ctrl+Q` |

## 🧱 技术栈

| 层 | 技术 |
| --- | --- |
| GUI 框架 | PySide6（Qt 6） |
| Markdown 解析 | Python-Markdown |
| 内容净化 | nh3（ammonia） |
| 代码高亮 | Pygments |
| 数学 / 图表 | KaTeX、Mermaid（经 Qt WebEngine，离线内置） |
| 打包 | PyInstaller + NSIS |

## 📁 目录结构

```
mdnote/
  __main__.py           python -m mdnote 入口
  app.py                QApplication / 单实例
  config.py             用户数据与资源路径、更新清单地址
  core/                 设置、文件读写、字数统计
  editor/               块模型、源码编辑器、WebEngine 视图，web/ 为渲染页面
  resources/            应用图标
  services/             Markdown 引擎、净化、图片、检索、导出、插件、更新
  ui/                   主窗口、标签会话、侧边栏、状态栏、查找栏、对话框、主题
launch.py               打包入口
scripts/
  prepare_installer.py  生成 NSIS 安装文件清单（构建第 2 步）
installer/setup.nsi     NSIS 安装程序脚本（构建第 3 步）
tests/                  单元测试与 WebEngine 集成测试
examples/plugins/       Python-Markdown 扩展示例
docs/                   完整技术文档
dist/MdNote/            PyInstaller 打包产物（构建生成，已被 Git 忽略）
```

`mdnote/editor/web/` 是渲染页面本体：`index.html`、`app.js`、`code_editor.js`、
`html_to_md.js`、`styles.css`；`vendor/` 内置 KaTeX、Mermaid 及其字体，代码高亮调色板
直接写在 `styles.css`，因此排版与高亮完全离线可用。

## 📚 技术文档

| 文档 | 内容 |
| --- | --- |
| [架构设计](docs/architecture.md) | 进程 / 线程模型、分层、模块职责、桥接契约、关键流程 |
| [数据模型](docs/data-model.md) | 块模型、块类型、偏移与间隙不变量、编辑变换 |
| [性能设计](docs/performance.md) | 渲染、防抖节流、缓存、长文档优化、实测数据 |
| [安全模型](docs/security.md) | 威胁模型、进程隔离、净化管线、导航控制 |
| [扩展开发](docs/plugin-development.md) | Python-Markdown 扩展机制与完整示例 |
| [开发指南](docs/development.md) | 环境、调试、测试、规范、构建与发版 |

## ❓ 常见问题

**Q：点击文字能直接编辑吗？**
可以。渲染后模式下点击任意位置即进入该块编辑，光标落在点击处；点别处或按 Esc 恢复排版。

**Q：需要联网吗？**
不需要。KaTeX、Mermaid 等资源已离线内置，日常写作与排版完全离线可用。

**Q：两种模式会丢内容吗？**
不会。两种模式共用同一份文档，`Ctrl+/` 切换只是整体切换显示与编辑方式。

**Q：图片如何保存？**
拖拽或粘贴图片会自动写入文档所在目录下配置的图片文件夹（默认 `assets`），并插入引用；
可在设置中改为绝对路径。

**Q：为什么安装包较大？**
排版依赖 Qt WebEngine（Chromium 内核）运行时，这是固定成本；应用自身代码很小。

**Q：编译安装包时报 `could not find: "generated-files.nsh"`？**
说明跳过了生成文件清单这一步。`installer/generated-files.nsh` 是生成产物且已被 Git
忽略，克隆仓库后并不存在：先运行 `python scripts/prepare_installer.py`，再
`makensis installer/setup.nsi`。完整步骤与其它编译报错见上文「构建与安装」。

## 🗺️ 能力状态

- **已支持**：多标签、文件夹检索、超长文档按需排版、七套主题、自定义扩展、
  导出与自动更新，见上「功能一览」与[扩展与插件开发](docs/plugin-development.md)。
- **发版流程**：打包 → 生成文件清单 → 编译安装 → 生成并上传更新清单，
  见上文「构建与安装」；版本号以 `mdnote/__init__.py` 的 `__version__` 为准。
- **验证边界**：打包与安装主要在 Windows 验证；macOS / Linux 可运行源码版，
  安装包与自动更新尚未在非 Windows 平台验证。

## 📄 许可证

[MIT](LICENSE)
