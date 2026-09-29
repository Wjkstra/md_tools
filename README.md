# MdNote

> 一款类 Typora 的 Markdown 文档编辑 / 阅读工具，基于 **Electron + TypeScript + electron-vite** 构建。
> 核心设计目标：**可用性、性能、可扩展性、安全性**，长文档低负载，严防内存泄漏。

## 📖 项目介绍

MdNote 把「写作」与「排版」合二为一：未聚焦的内容块直接显示排版结果，
点击任意段落即临时展开该块的 Markdown 源码，离开自动渲染——无需在「编辑区 / 预览区」之间来回切换。

同时支持一键切换全文档源码模式、自动目录、可视化表格、190+ 语言代码高亮、
LaTeX 数学公式、Mermaid 图表、YAML Front Matter、专注 / 打字机模式，
以及 PDF / HTML / 图片导出与 Pandoc 扩展格式。

### 设计亮点

- ⚡ **视口虚拟化**：无论文档多长，DOM 中只保留屏幕附近的块。实测 **60,000 块**文档仅挂载 25~35 行
- 🧩 **块级文档模型**：纯函数解析，偏移可逆，规范文本是唯一事实源
- 🛡️ **纵深安全防护**：沙箱进程 + contextIsolation + DOMPurify 净化 + 自定义协议白名单 + 严格 CSP
- ♻️ **无泄漏生命周期**：统一 `Lifetime` 管理监听 / Observer / 定时器 / 订阅，卸载即释放
- 🔌 **插件可扩展**：markdown-it 插件机制，外部插件运行在沙箱中，设置中显式启停

## ✨ 功能特性

### 编辑与渲染

- **实时（所见即所得）模式**：点击块展开源码、离开自动渲染
- **源码模式**：`Ctrl+/` 切换，CodeMirror 6 全文档编辑
- 完整基础语法：标题、加粗 / 斜体 / 删除线、行内代码、引用、有序 / 无序 / 任务列表、链接、图片、分隔线、内嵌 HTML
- 空格触发快捷输入：`# `、`- `、`> `、`1. `、`- [ ] `、```` ``` ````、`$$`
- 符号自动配对、智能标点（弯引号，可开关）

### 高级功能

- **`[toc]` 自动目录**：随标题修改更新，点击跳转
- **代码块**：highlight.js 提供 190+ 语言高亮、行号开关、一键复制
- **数学公式**：KaTeX 渲染行内 `$...$` 与块级 `$$...$$`
- **Mermaid 图表**：流程图 / 时序图 / 甘特图 / 饼图等
- **可视化表格**：单元格选中 / 编辑、拖拽列宽、右键增删行列与对齐、`Tab` 跨格导航
- **YAML Front Matter**：头部元信息解析展示
- **会话恢复**：重启自动打开上次文件 / 文件夹，恢复窗口与侧边栏状态
- **自动保存**：停顿 1 秒静默落盘（可开关）

### 沉浸式写作

- 专注模式（`F8`）：仅当前块高亮，其余变暗
- 打字机模式（`F9`）：光标保持屏幕中央
- 大纲侧边栏：章节跳转，当前章节实时高亮
- 状态栏：字数、字符数、行数、预估阅读时长、保存状态

### 导入导出

- 导出 **HTML / PDF / PNG / JPEG**（PDF 支持页边距、横向、页码、目录选项）
- 安装 **Pandoc** 后支持 **Word (.docx) / ePub / LaTeX / ODT**
- 图片拖拽 / 粘贴自动落盘（可配置图片目录与相对 / 绝对路径）

## 🚀 安装与运行

### 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Node.js | **≥ 18**（推荐 20 / 22 LTS） | 含 npm |
| 操作系统 | Windows 10+ / macOS 11+ / Linux | 主要在 Windows 上测试 |
| Pandoc | 可选（≥ 2.19） | 仅导出 docx / ePub / LaTeX / odt 时需要 |

检查环境：

```bash
node -v   # 期望 v18 以上
npm -v
```

### 快速开始

```bash
# 1. 获取代码后进入项目目录
cd md_tool

# 2. 安装依赖（首次运行需要）
npm install

# 3. 启动开发模式（热更新）
npm run dev
```

启动后窗口自动打开并载入欢迎文档（或恢复上次会话）。

### 生产构建与运行

```bash
npm run build      # 构建主进程 / preload / 渲染进程到 out/
npm start          # 以生产方式运行构建产物
```

### 打包桌面安装程序

```bash
npm run dist       # electron-builder 打包，产物输出到 release/
```

Windows 下生成 NSIS 安装程序；如需其他平台格式，修改 `package.json` 中的 `build` 配置。

### 可选：安装 Pandoc

- Windows：`winget install --id JohnMacFarlane.Pandoc`，或访问 <https://pandoc.org/installing.html>
- 安装后重启 MdNote，导出菜单中的 docx / ePub / LaTeX / odt 自动可用

## ⌨️ 快捷键

| 功能 | 快捷键 |
| --- | --- |
| 新建 / 打开 / 保存 | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` |
| 打开文件夹 / 另存为 | `Ctrl+Shift+O` / `Ctrl+Shift+S` |
| 加粗 / 斜体 | `Ctrl+B` / `Ctrl+I` |
| 删除线 / 行内代码 | `Ctrl+Shift+X` / `Ctrl+Shift+\`` |
| 代码块 / 插入图片 | `Ctrl+Shift+K` / `Ctrl+Shift+I` |
| 链接 | `Ctrl+K` |
| 查找 | `Ctrl+F` |
| 切换实时 / 源码视图 | `Ctrl+/` |
| 侧边栏 | `Ctrl+J` |
| 专注模式 / 打字机模式 | `F8` / `F9` |
| 字号缩放 / 恢复 | `Ctrl+=` / `Ctrl+-` / `Ctrl+0` |
| 设置 | `Ctrl+,` |

## 🧱 技术栈

| 层 | 技术选型 |
| --- | --- |
| 应用框架 | Electron 33 |
| 构建工具 | electron-vite 2 + Vite 5 |
| 语言 | TypeScript 5（strict 模式） |
| Markdown 解析 | markdown-it 14 |
| 内容净化 | DOMPurify 3 |
| 代码高亮 | highlight.js 11（动态加载，190+ 语言） |
| 数学公式 | KaTeX |
| 图表 | Mermaid 11（按图表类型动态分包） |
| 源码编辑器 | CodeMirror 6 |
| 元信息 | yaml |
| 打包分发 | electron-builder |

## 📚 项目文档

完整文档位于 [`docs/`](docs/) 目录（可直接用 MdNote 打开查看，支持 Mermaid 渲染）：

| 文档 | 内容 |
| --- | --- |
| [架构设计](docs/architecture.md) | 进程模型、分层架构、模块职责、IPC 通道、关键流程 |
| [数据模型](docs/data-model.md) | 块模型设计、块类型、偏移与间隙不变量、编辑变换 |
| [性能设计](docs/performance.md) | 虚拟化机制、长文档负载优化、缓存策略、基准数据 |
| [安全模型](docs/security.md) | 威胁模型、沙箱隔离、净化管线、CSP 与安全清单 |
| [插件开发](docs/plugin-development.md) | 扩展点、插件结构、API、完整示例 |
| [开发指南](docs/development.md) | 环境搭建、目录结构、调试、测试、编码规范、发版 |

## 🗺️ Roadmap

- [ ] 多标签页 / 多窗口文档管理
- [ ] 全局搜索（文件夹内全文检索）
- [ ] 更多内置主题与主题市场
- [ ] 自动更新（electron-updater）
- [ ] 插件扩展点增强（命令、快捷键、自定义块、状态栏）
- [ ] macOS / Linux 打包验证

## 📄 许可证

[MIT](LICENSE)
