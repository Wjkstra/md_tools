# 开发指南

面向贡献者的上手文档：环境搭建、常用命令、调试测试、编码规范、
功能添加示例与发版流程。

## 1. 环境准备

| 工具 | 版本 | 安装 |
| --- | --- | --- |
| Node.js | ≥ 18（推荐 22 LTS） | <https://nodejs.org/> |
| npm | 随 Node（≥ 10） | — |
| Git | 任意近期版本 | <https://git-scm.com/> |
| Pandoc | 可选 | <https://pandoc.org/installing.html> |

```bash
git clone <repo> md_tool
cd md_tool
npm install
```

## 2. 常用命令

```bash
npm run dev        # 开发模式：主/preload/渲染全部 watch，渲染热更新
npm run build      # 生产构建到 out/（main、preload、renderer）
npm start          # 运行生产构建产物
npm run typecheck  # 两个 tsconfig 分别做严格类型检查（CI 必跑）
npm run dist       # 构建 + electron-builder 打包安装程序到 release/
```

## 3. 配置文件说明

| 文件 | 作用 |
| --- | --- |
| `electron.vite.config.ts` | 三个构建目标（main / preload / renderer）的入口、`@shared` 路径别名 |
| `tsconfig.json` | 解决方案文件，引用下面两个子配置 |
| `tsconfig.node.json` | 主进程 + preload + 构建脚本（含 node / electron-vite 类型） |
| `tsconfig.web.json` | 渲染进程（DOM lib，`@renderer` / `@shared` 路径） |
| `package.json → build` | electron-builder 的 appId、产物目录与平台目标 |

> 路径别名同时在 tsconfig 与 vite 配置中声明，两处需保持一致。

## 4. 调试

### 渲染进程

- `npm run dev` 下窗口可按 `Ctrl+Shift+I` 打开 DevTools
- 渲染进程的 console 会**转发到启动终端**（主进程注册了 `console-message`）
- Vite HMR 对渲染侧 TS / CSS 改动即时生效

### 主进程 / preload

- 主进程改动后 electron-vite 自动重启 Electron
- preload 改动同样触发重启（preload 无法热替换）
- preload 加载错误会在终端打印 `[preload error]`

### 开发期实用手段

- 临时菜单「View → Force Reload」可重载页面（会重新读取插件与设置）
- 冒烟模式见下节，可驱动完整自动化流程而无需手动点击

## 5. 测试

### 5.1 功能夹具

`test/fixture.md` 覆盖全部块类型（frontmatter、toc、标题、引用、列表 / 任务、
表格、代码、Mermaid、公式、分隔线）。

### 5.2 SMOKE 自动化

主进程在 `SMOKE=1` 时启动后自动执行：

1. 打开夹具 → 等待异步渲染 → 输出块计数探测（`__probe`）
2. 任务复选交互
3. 装载 **60,000 块长文档**，输出装载耗时与顶 / 中 / 底挂载行数
4. 重新打开夹具，执行「点击 → 输入 → 失焦提交」编辑闭环校验
5. 退出（退出码可判定成败）

运行：

```bash
npm run build
# Windows PowerShell
$env:SMOKE=1; npx electron .
# Git Bash / macOS / Linux
SMOKE=1 npx electron .
```

测试钩子（`__open / __probe / __loadText / __toggleFirstTask / __editTest`）
仅在页面 URL 带 `?smoke=1` 时挂到 `window.__app`，正常使用不暴露。

### 5.3 添加测试

- 新块类型：在夹具中加入示例，并在 `__probe()` 中增加选择器计数
- 新交互：在 `App` 增加 `__xxx` 测试方法（分发合成事件 + 断言结果），
  在 `src/main/index.ts` 的冒烟脚本中加入步骤与输出

## 6. 编码规范

### TypeScript

- **strict 模式**，`noUnusedLocals / noUnusedParameters` 开启——不允许残留死代码
- 禁止 `any` 逃避类型；确需时用 `unknown` 并收窄
- 优先 `interface` 描述对外契约，联合类型描述枚举状态
- 跨进程共享类型一律放 `src/shared/types.ts`

### 资源管理（强制）

- 任何 `addEventListener` 必须走 `Lifetime.on`（或显式登记释放）
- Observer / 定时器 / 订阅 / Blob URL / 临时文件在作用域结束时释放
- 新增缓存**必须有容量上限**；新增异步任务必须支持取消（AbortSignal）

### 风格

- 与周边代码保持一致：4 空格缩进风格（跟随现有文件）、单引号
- 公共 API 写简洁文档注释；注释解释「为什么」，不复述「做什么」
- 文件名：模块 `kebab-case.ts`；类 `PascalCase`；常量 `UPPER_SNAKE`
- UI 文本使用中文；代码标识符使用英文

### 提交

- 一个提交解决一件事；消息描述用户可感知的变化
- 提交前本地跑通：`npm run typecheck` 与 SMOKE

## 7. 添加一个新功能（走查）

### 例 A：新增一个设置项（如「编辑确认音」）

1. `src/shared/types.ts`：`AppSettings` 加字段 + `DEFAULT_SETTINGS` 默认值
2. 读取消费处直接访问 `settingsService.current.xxx`
3. 设置 UI：`src/renderer/src/ui/dialogs.ts` 中加 `toggleRow(...)`
4. 无需改引擎；设置变更通过 `settingsService.onChange` 通知

### 例 B：新增一个菜单 / 快捷键动作

1. `src/shared/types.ts` 的 `MenuAction` 加成员
2. `src/main/menu.ts`：加菜单项与 `accelerator`（click 统一 send）
3. `src/renderer/src/app.ts` 的 `handleAction` 加分支
4. 重能力放编辑器 / 服务层，App 只做编排

### 例 C：新增一种块类型

见 [数据模型 · 扩展块类型](data-model.md#8-扩展块类型)。

## 8. 设置字段参考

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `theme` | string | 主题 id（github-light / github-dark / sepia / midnight） |
| `fontSize` | number | 正文字号（12–28） |
| `tabSize` | number | Tab 对应空格数 |
| `codeLineNumbers` | boolean | 代码块显示行号 |
| `mermaid` | boolean | Mermaid 围栏渲染为图表 |
| `smartPunctuation` | boolean | 直引号自动转弯引号 |
| `focusMode` / `typewriterMode` | boolean | 专注 / 打字机模式 |
| `autoBracket` | boolean | 符号自动配对 |
| `imageFolder` | string | 图片落盘目录名 |
| `imagePathType` | `'relative' \| 'absolute'` | 插入图片使用的路径形式 |
| `highlightMark` | boolean | 启用 `==高亮==` 内置扩展 |
| `autoSave` | boolean | 停顿 1 秒自动保存 |
| `sidebarVisible` / `sidebarTab` | boolean / `'files' \| 'outline'` | 侧边栏状态 |
| `lastFile` / `lastFolder` | string \| null | 会话恢复目标 |
| `enabledPlugins` | string[] | 已启用插件名 |
| `recentFiles` / `recentFolders` | string[] | 最近打开记录 |

## 9. 构建与发版

```bash
# 1. 版本号
npm version minor    # 或 patch / major（会更新 package.json 并打 tag）

# 2. 干净构建 + 类型检查
npm run typecheck
npm run dist
```

- 产物：`release/`（Windows NSIS 安装程序及 yaml 元数据）
- 跨平台打包建议在对应系统上执行，或配置 CI 矩阵
- 应用名 / appId / 图标在 `package.json` 的 `build` 中配置

## 10. 常见问题排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 页面无内容、`window.mdnote` undefined | 检查终端 preload 报错；确认 preload 产物与主进程引用文件名一致（当前为 CJS `index.js`） |
| 端口 5173 被占用 | 关闭上一个 dev（Electron 残留进程：任务管理器结束 electron），或修改 dev 端口 |
| 修改主进程代码没反应 | electron-vite 会自动重启；若异常，终端 `Ctrl+C` 后重新 `npm run dev` |
| SMOKE 无输出 | 确认在项目根目录运行、`test/fixture.md` 存在；查看终端 renderer 错误行 |
| 打包后白屏 | 多为资源路径问题；确认使用 `__dirname` 相对引用且 `files` 包含 out/ |
| 退出后仍有 electron 进程 | Windows 下可用 `Get-Process electron \| Stop-Process -Force` 清理 |

## 11. 相关文档

- [架构设计](architecture.md)
- [数据模型](data-model.md)
- [性能设计](performance.md)
- [安全模型](security.md)
- [插件开发](plugin-development.md)
