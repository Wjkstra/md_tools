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

- 双模式：渲染后所见即所得 / 整篇源码，`Ctrl+/` 切换
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
- **代码块**：Pygments 语法高亮、行号开关、一键复制
- **数学公式**：KaTeX 渲染行内 `$...$` 与块级 `$$...$$`
- **Mermaid 图表**：流程图、时序图、甘特图、饼图等
- **可视化表格**：单元格直接编辑、`Tab` 跨格导航、失焦自动回写；
  菜单可在下方插入行 / 右侧插入列、删除行列、设置列对齐
- **`[toc]` 自动目录**：随文档更新，点击跳转
- **YAML Front Matter**：头部元信息解析展示

> KaTeX、Mermaid 等资源**已离线内置**，无需联网即可使用。

### 沉浸式写作

- **专注模式**（`F8`）：仅当前块高亮，其余变暗
- **打字机模式**（`F9`）：光标保持在屏幕中部
- 侧边栏：文件树（双击打开）+ 大纲（点击跳转、当前章节高亮）
- 状态栏：保存状态、字数 / 字符 / 行数、阅读时长、当前模式

### 文件、图片与导出

- 新建 / 打开 / 保存 / 另存为 / 打开文件夹
- 自动保存（可开关）、会话与最近文件恢复
- 图片**拖拽 / 粘贴自动落盘**（可配置图片目录与相对 / 绝对路径）
- 外部程序修改当前文件时提示重新载入
- 导出 **HTML / PDF / PNG / JPEG**
- 安装 **Pandoc** 后可导出 **Word (.docx) / ePub / LaTeX / ODT**

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
python tests/test_editor.py        # 编辑器变换纯函数回归测试
python tests/test_live_editor.py   # WebEngine 集成测试（真实页面交互）
python tests/test_live_editor.py  # Qt WebEngine 交互、保存与模式切换回归测试
```

## 📦 构建与安装

### 打包应用目录

```bash
pip install pyinstaller
pyinstaller mdnote.spec --noconfirm
```

产物位于 `dist/MdNote/`，运行其中的 `MdNote.exe`。

### 生成安装程序

使用 NSIS 编译安装脚本：

```bash
makensis installer/setup.nsi
```

将生成单个安装程序，**安装时可自定义安装路径**，并创建开始菜单快捷方式、
注册卸载程序；卸载时清理安装内容。

> 安装包体积主要来自 Qt WebEngine（Chromium 内核）运行时，
> 这是高质量 HTML/CSS 排版所必需的部分；应用自身代码占比很小。

### 可选：Pandoc

- Windows：`winget install --id JohnMacFarlane.Pandoc`
- 或访问 <https://pandoc.org/installing.html>
- 安装后重启应用，导出菜单中的 docx / epub / LaTeX / ODT 即可用

## ⌨️ 快捷键

| 功能 | 快捷键 |
| --- | --- |
| 新建 / 打开 / 保存 | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` |
| 打开文件夹 / 另存为 | `Ctrl+Shift+O` / `Ctrl+Shift+S` |
| 撤销 / 重做 | `Ctrl+Z` / `Ctrl+Y` |
| 加粗 / 斜体 / 删除线 | `Ctrl+B` / `Ctrl+I` / `Ctrl+Shift+X` |
| 行内代码 / 链接 | `Ctrl+Shift+\`` / `Ctrl+K` |
| 插入代码块 / 表格 / 分隔线 / 图片 | `Ctrl+Shift+K` / 菜单 / 菜单 / `Ctrl+Shift+I` |
| 切换任务项 / 编辑当前块源码 | `Ctrl+Shift+Enter` / `F2` |
| 查找 / 替换 / 全选 | `Ctrl+F` / `Ctrl+H` / `Ctrl+Shift+A` |
| 查找下一个 / 上一个 | `F3` / `Shift+F3` |
| 切换源码 / 渲染后模式 | `Ctrl+/` |
| 命令面板 | `Ctrl+Shift+P` |
| 侧边栏：切换 / 文件树 / 大纲 / 返回编辑器 | `Ctrl+J` / `Ctrl+Shift+E` / `Ctrl+Shift+L` / `Ctrl+Alt+E` |
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
  app.py                QApplication / 单实例
  config.py             用户数据与资源路径
  core/                 设置、字数统计
  editor/               块模型、编辑变换、源码编辑器、WebEngine 排版及 web 资源
  services/             Markdown 引擎、图片服务、导出
  ui/                   主窗口、侧边栏、状态栏、查找栏、对话框
launch.py               打包入口
tests/test_editor.py    编辑器变换回归测试
installer/setup.nsi     NSIS 安装程序脚本
docs/                   完整技术文档
```

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

## 🗺️ 规划方向

- 插件自动加载器（设置中勾选启停 Python-Markdown 扩展）
- 超长文档的分块按需排版
- 多标签 / 多窗口文档管理
- 文件夹全文检索、更多内置主题、自动更新

## 📄 许可证

[MIT](LICENSE)
