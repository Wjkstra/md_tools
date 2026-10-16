# 测试

在仓库根目录执行，Python 依赖见 requirements.txt；JavaScript 用例使用 Node 内置测试器。

    python -m unittest discover -s tests -p "test_*.py"
    node --test tests/test_html_to_md.js tests/test_code_editing.js tests/test_md_inline.js

无显示环境使用：

    $env:QT_QPA_PLATFORM = "offscreen"
    $env:QTWEBENGINE_CHROMIUM_FLAGS = "--disable-gpu"

## 2026-10-10 验证结果

- Python：123 个 unittest 用例通过，1 个因 Windows 不支持创建目录符号链接而跳过。
- JavaScript：33 个用例全部通过（html→Markdown 序列化、代码编辑、行内即时渲染）。
- 全量 Python 回归使用临时设置文件，关闭自动更新检查，未修改用户设置。
- Qt WebEngine 的 Chromium 沙箱保持启用；离屏运行产生 GPU/GLES 日志，退出码为 0。
- 已查看真实页面的浅色宽屏与深色窄窗口截图，确认代码编辑区没有围栏符号与焦点边框。

## 编辑器回归覆盖

tests/test_code_table_experience.py 使用真实 QWebEngineView / QWebChannel 与 QTest 键盘事件，覆盖：

- 代码围栏隐藏、正文按字面保存、语言选择与离线高亮。
- C/C++ 自动缩进、括号内换行、Python 冒号缩进、继续换行不累加缩进。
- 单行与多行 Tab / Shift+Tab、成对符号删除、已有引号跳过、原生撤销。
- 高亮更新保持编辑 DOM、光标与撤销；返回编辑器不再重载页面。
- 代码 Ctrl+A 局部全选、Ctrl+Enter 返回正文。
- 多行代码粘贴保持纯文本、输入后立即读取、首尾空行、未闭合围栏与内嵌反引号。
- 表格 Ctrl+Enter 新增行、Alt+Enter 新增列、光标跟随、继承列对齐、撤销。
- Tab 跨格填写、末格创建新行、表头插行、菜单删除与对齐。
- 代码插入菜单、输入围栏后回车转换、1680px / 600px 自适应布局、行号设置。
- IME 组字事件不会触发自动配对；关闭自动配对设置后尊重用户选择。

tests/test_code_editing.js 验证语言预设、注释/字符串语境、选区换行和多行缩进；
tests/test_html_to_md.js 验证格式、表格空格与竖线、代码空行和安全围栏。
其余 Python 套件覆盖源编辑器、保存与外部变更、多标签、搜索、设置、导出及服务安全。

## 验证边界

IME 用事件模拟覆盖，未用实体输入法逐一验证。离屏测试不能证明真实显卡上的输入延迟。
代码语言预设提供缩进、符号配对与语法高亮，不提供编译器诊断或 IDE 补全。
超过 100,000 字符的单个代码块显示纯文本，避免高亮阻塞界面。
