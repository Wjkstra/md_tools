# 开发指南

面向贡献者的上手文档：环境搭建、常用命令、调试、测试、
编码规范，以及构建安装程序与发版流程。

## 1. 环境准备

| 工具 | 版本 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.10（推荐 3.11 / 3.12） | <https://www.python.org/> |
| pip | 近期版本 | 随 Python |
| Git | 任意近期版本 | <https://git-scm.com/> |
| PyInstaller | 随 requirements / dev 安装 | 打包 |
| NSIS | 3.x | 生成安装程序 |
| Pandoc | 可选 | 导出 docx / epub 等 |

建议使用虚拟环境：

```bash
git clone <repo> md_tool
cd md_tool

python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Git Bash / Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install pyinstaller      # 仅开发打包时需要
```

## 2. 常用命令

```bash
python -m mdnote              # 直接运行应用（源码方式，改代码即生效）
python tests/test_editor.py   # 运行编辑器变换回归测试
pyinstaller mdnote.spec       # 打包出 dist/MdNote 目录
```

## 3. 配置与模块说明

| 文件 / 目录 | 作用 |
| --- | --- |
| `mdnote/config.py` | 用户数据目录与 Web 资源路径，兼容 PyInstaller 环境 |
| `mdnote/app.py` | QApplication、单实例守护 |
| `mdnote/core/settings.py` | 设置数据类、JSON 持久化、变更通知 |
| `mdnote/editor/webview.py` | 实时模式、QWebChannel 桥、渲染净化 |
| `mdnote/editor/web/` | 排版页面（HTML/CSS/JS）与离线资源 |
| `mdnote.spec` | PyInstaller 打包配置（入口、数据、excludes） |
| `installer/setup.nsi` | NSIS 安装程序脚本 |

## 4. 调试

### 应用

- 直接 `python -m mdnote` 运行，在终端查看异常堆栈
- 排版逻辑在独立 WebEngine 进程；页面行为可在 `mdnote/editor/web/app.js` 中调整
- 渲染内容若与预期不符，先确认是否被 `editor/webview.py` 的净化规则调整

### 独立验证解析与净化

```python
from mdnote.services.markdown_engine import markdown_engine
print(markdown_engine().render("# 标题\n\n正文"))

from mdnote.editor.webview import _safe_html
print(_safe_html("<p onclick='x'>a</p>"))
```

## 5. 测试

详见独立的 [测试文档](testing.md)。两层套件：

| 套件 | 覆盖 | 命令 |
| --- | --- | --- |
| `tests/test_editor.py` | 纯函数：各块类型回车、合并、缩进、空格触发、包裹、序列化往返（33 项） | `python tests/test_editor.py` |
| `tests/test_live_editor.py` | 真实 WebEngine 页面端到端交互：输入、块切换、表格、命令面板、焦点导航、保存等（40 项） | `python -m unittest tests.test_live_editor` |

提交前应确保两层均通过。

### 5.1 添加测试

- 新变换：在 `tests/test_editor.py` 按现有 `check(...)` 形式添加纯函数断言
- 新交互：先在 `transforms.py` 以纯函数实现，再加测试，最后接入页面脚本

> 编辑变换优先写成**纯函数**（输入文本与偏移，输出文本与光标），
> 便于测试与复用，不直接依赖页面或控件。

## 6. 编码规范

### Python

- 使用类型注解；公共 API 写简洁文档字符串
- 数据结构优先使用 `dataclass`
- 不保留无用导入 / 死代码
- 注释解释「为什么」，不复述「做什么」

### 命名

| 类别 | 风格 | 示例 |
| --- | --- | --- |
| 模块文件 | `snake_case.py` | `block_model.py` |
| 类 | `PascalCase` | `MainWindow` |
| 函数 / 变量 | `snake_case` | `build_model` |
| 常量 | `UPPER_SNAKE` | `_ALLOWED_TAGS` |

UI 面向用户的文本使用中文；代码标识符使用英文。

### 资源与性能

- 连续输入触发的派生计算（统计、大纲、自动保存）一律防抖
- 缓存必须有界；耗时操作放入工作线程，不在工作线程直接操作控件
- 临时文件 / 媒体资源在任务结束后清理

## 7. 添加一个新功能（走查）

### 新增一个设置项

1. `core/settings.py` 的 `AppSettings` 增加字段与默认值
2. 消费处读取 `settings_service().current.xxx`
3. 在设置面板加入对应控件；变更通过 `patch()` 持久化并通知

### 新增一种编辑行为

1. 在 `editor/transforms.py` 增加纯函数并返回 `TransformResult`
2. 在 `tests/test_editor.py` 添加断言
3. 在 `editor/webview.py` 的 `transform` 分派命令
4. 在 `web/app.js` 绑定对应按键

### 新增一种 Markdown 语法

见 [插件开发](plugin-development.md)，通过 Python-Markdown 扩展实现。

## 8. 构建安装程序与发版

### 8.1 打包应用目录

```bash
pyinstaller mdnote.spec --noconfirm
```

产物 `dist/MdNote/` 包含可执行文件、Qt 运行时与 Web 资源。

### 8.2 生成安装程序

使用 NSIS 编译 `installer/setup.nsi`（支持用户选择安装目录、创建快捷方式、
生成卸载程序）：

```bash
makensis installer/setup.nsi
```

产物为单个安装程序 exe。

### 8.3 发版前检查

- [ ] `python tests/test_editor.py` 全部通过
- [ ] `python -m mdnote` 手工验证核心编辑流程
- [ ] PyInstaller 打包后可运行
- [ ] 安装程序可在自定义目录安装、可卸载
- [ ] 版本号与文档同步

## 9. 常见问题排查

| 现象 | 处理 |
| --- | --- |
| 启动报 `No module named mdnote` | 确认在仓库根目录运行，或激活了虚拟环境 |
| 页面内容被改变 | 查看 nh3 净化白名单；确认标签 / 属性是否允许 |
| 外部链接打不开 | 确认系统默认浏览器；外链经 `openExternal` 仅放行 http(s)/mailto |
| 已有图片不显示 | 相对图片依赖文档目录；确认文件已保存且图片路径正确 |
| 打包后体积很大 | 主要为 Qt WebEngine 运行时；确认 `mdnote.spec` 的 excludes 生效 |
| 再次启动无窗口 | 可能已有实例运行（单实例守护） |

## 10. 相关文档

- [架构设计](architecture.md)
- [数据模型](data-model.md)
- [性能设计](performance.md)
- [安全模型](security.md)
- [插件开发](plugin-development.md)
