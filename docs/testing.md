# 测试

MdNote 有两层自动化测试：**纯函数单元测试**与 **WebEngine 集成测试**。
运行前请先安装 `requirements.txt` 中的依赖，并在仓库根目录执行。

## 运行

```powershell
# ① 编辑器变换纯函数回归（无需 GUI，毫秒级）
python tests/test_editor.py

# ② 插件加载器
python tests/test_plugin_loader.py

# ③ WebEngine 集成测试（真实页面 + QWebChannel）
python -m unittest tests.test_live_editor
```

在 CI / 无显示环境中，集成测试会自动使用离屏平台：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu"
python -m unittest tests.test_live_editor
```

## 当前结果

| 套件 | 内容 | 用例数 | 结果 |
| --- | --- | --- | --- |
| `tests/test_editor.py` | 块解析、智能回车、合并、缩进、空格触发、包裹、序列化往返 | 33 项断言 | ✅ 通过 |
| `tests/test_plugin_loader.py` | 插件目录扫描、按名导入、扩展参与渲染、错误隔离 | 8 项断言 | ✅ 通过 |
| `tests/test_live_editor.py` | 真实 `QWebEngineView` + `QWebChannel` 的端到端交互 | 40 个测试 | ✅ 通过（约 27s） |

## 集成测试覆盖范围

测试驱动真实页面（部分操作经 DOM 事件注入，部分用 Qt 原生键盘事件），覆盖：

- **键盘输入与回车**：原生打字、回车、下一行继续输入；换行位置与光标
- **块切换**：方向键在多块间上下移动、`Ctrl+Home/End`、横向越界进入相邻块
- **智能回车**：段落 / 标题回车后的渲染、空行焦点与光标；列表续行、代码块内回车
- **选区**：回车 / 空格替换选区、反向选区、多行粘贴替换选区
- **表格**：`Tab` 遍历单元格、增删行列、列对齐保留、表格输入无需失焦即同步
- **命令面板**：键盘搜索、过滤并执行命令
- **焦点导航**：`F6` 区域循环、查找栏 `Esc`、侧边栏 `Esc` 返回编辑器
- **保存**：保持焦点时手动保存与自动保存都能读到未失焦的输入
- **撤销 / 重做**：草稿与提交后的历史、新输入使重做失效
- **编码**：Emoji / 中文的 UTF-16 与码点偏移换算；组字期间回车不拆分

测试写入临时目录，不操作用户文档；结束后清理临时页面与事件。

## 未覆盖（边界说明）

- 离屏环境存在 Chromium GPU 相关的上下文中的日志，不能据此判断真实显示性能
- PDF / 图片 / Pandoc 导出、复杂表格的高级格式、图片粘贴的端到端不在当前自动化范围内
- IME（输入法）组字通过事件级测试模拟，尚需不同输入法的人工验证

## 添加测试

- 新的纯函数变换：在 `tests/test_editor.py` 用现有 `check(...)` 形式添加断言
- 新的页面交互：在 `tests/test_live_editor.py` 添加 `test_...`，通过 `self.js(...)`
  驱动页面、`self.wait(predicate)` 等待异步结果
- 新增块类型时，优先在纯函数层覆盖解析逻辑，再在集成层验证交互
