**MdNote 多方面复评 — 2026-10-08**

评审对象为 D:/tools/md_tool 当前工作区源码，包括此前尚未提交的体验和可靠性改进。本轮覆盖数据保护、安全边界、编辑语义、文件和导出、设置、线程与性能、扩展、安装更新及测试。未修改业务源码，未安装或卸载程序，未重建发布产物。

结论：此前的原子写入、搜索线程退出保护、查找反馈及输入配对改进已有回归验证；但仍有可导致数据覆盖、格式丢失和无法启动的问题。建议先修复以下 P1，再处理导出、更新及长文档性能。测试通过不能视为发布路径已经验证。

优先级：P1 为数据丢失、活动内容安全边界或持续启动失败；P2 为功能错误、失败处理缺失和明显性能退化；P3 为较低影响的元数据或体验一致性问题。条件风险及未完成实机验证的事项另列。

**优先修复：5 项 P1**

1. **后台自动保存会静默覆盖外部修改。**
   位置：mdnote/ui/editor_session.py:68、93、114–124；mdnote/ui/main_window.py:695–709。
   开启自动保存，编辑 A 后切换 B，外部程序在 A 的定时器到期前修改 A；主窗口只监视 B，而 A 的独立自动保存仍运行，直接写入本地内容。切回 A 也没有重新比较磁盘基线。实际方法与 mock 验证得到：仅监视 B，外部版本被本地版本替换，dirty=False，提示列表为空。
   修复：追踪全部打开文件，并在手动保存与自动保存前比较磁盘版本和已知基线；冲突时保留本地修改、提供重新载入或另存副本。原子写入解决半写入问题，不能解决版本冲突。

2. **表格仅进入编辑再失焦就会丢失 Markdown 格式和链接。**
   位置：mdnote/editor/web/app.js:175–178、241–267，尤其第 254 行。
   blur 无条件尝试回写整张表格，序列化使用 textContent。含 **bold** 和 Markdown 链接的表格，点击单元格再点击外部，即使没有输入，也会变成纯文本 bold、website，链接地址丢失，随后可被保存。
   验证使用原始 JavaScript 函数和 DOM mock，确认 focus→blur 触发上述无格式回写；不是本轮真实浏览器交互验证。
   修复：保留各单元格的原始 Markdown，未修改不提交，只更新实际修改的单元格；富文本序列化必须保留链接、强调、代码、图片和换行。

3. **卸载会递归删除安装目录中的用户原有文件。**
   位置：installer/setup.nsi:28、47–49、103。
   安装目录可自行选择，没有专用目录或已有内容校验；卸载使用 RMDir /r "$INSTDIR"。选择已有资料目录安装后，卸载会连同原有文件一起删除。结论来自完整安装脚本检查，未实际执行卸载。
   修复：安装时约束专用目录；按安装文件清单卸载，仅删除应用拥有的文件，最后只删除空目录。不要依赖安装目录一定没有用户内容。

4. **导出绕过预览的 HTML 净化，保留脚本与事件属性。**
   位置：mdnote/services/exporter.py:29–46、87–101；对照 mdnote/editor/webview.py:69–77。
   build_standalone_html 直接使用 Markdown 引擎输出；实测包含 onerror 的 img 和 script 均原样进入导出 HTML。图片导出又把同一份内容加载到新的 QWebEngineView，未使用预览净化与导航保护。导出文件因此可携带活动内容。
   修复：预览和所有导出统一内容净化规则，转义目录标题；图片导出使用受控页面并限制导航。保留公式和图表所需的受信运行资源，但不允许文档注入脚本。未证明原生代码执行或系统权限逃逸。

5. **插件注册异常可导致后续启动持续失败。**
   位置：mdnote/services/plugin_loader.py:98–107；mdnote/services/markdown_engine.py:67–68；mdnote/ui/main_window.py:54–55。
   加载器只隔离导入和工厂实例化错误。合法 Extension 的 extendMarkdown 抛异常时，load_enabled 的错误列表为空，reconfigure 原样抛出。启用状态已保存，下一次启动仍失败，需要手动修改设置禁用插件。
   验证使用受控 Extension mock，没有运行外部插件。
   修复：引擎注册阶段也隔离异常，保留最后可用引擎；启动失败时进入禁用故障插件的恢复模式。Python 插件属于受信代码，此项是可恢复性缺陷。

**编辑和定位：P2**

| 问题 | 位置和复现证据 | 修复方向 |
| --- | --- | --- |
| 点击第二个任务项却切换第一项；大写 [X] 无法取消 | app.js:532 只传块索引和 task 布尔值；webview.py:281 固定选择第一个 checkbox，283 只识别小写 x。真实 LiveDocument 的两行任务列表验证：点击第二项的路径只能修改第一项。 | 桥接传具体任务行或任务索引，统一大小写识别。 |
| Shift+Tab 删除正文全部 Tab，且忽略缩进宽度 | transforms.py:123 使用 ^ {1,4} 或未锚定的 Tab 分支。实测 indent_line("    a\tb\tc", 7, 2, True) 得到 "abc"；宽度 2 删四空格，宽度 8 仍只删四空格。 | 仅处理当前行行首缩进，按 tab_size 删除，并保持合理光标位置。 |
| 源码行号跳转受视觉换行影响 | source_editor.py:219 使用 QTextCursor.Down。Qt 离屏验证：宽 180，第一行含 "long " × 80，goto_line(2) 实际仍在 blockNumber=0，position=5，应在第二逻辑行。 | 使用 findBlockByNumber(line - 1)，验证自动换行开启时的大纲和搜索定位。 |
| emoji 前缀使渲染模式行定位偏移错误 | main_window.py:539–540 将 Python 字符偏移直接发到 app.js:680 的浏览器光标。临时文件“😀\nTARGET”定位第 2 行发送偏移 2，DOM 的 UTF-16 偏移应为 3。 | 集中实现 Python 字符偏移与 UTF-16 偏移的边界转换；覆盖所有桥接入口。 |
| Mermaid 代码围栏无法进入图表转换 | markdown_engine.py:38–43 的 codehilite 输出没有 language-mermaid，app.js:383、446 仅按该类查找。实际 MarkdownEngine 输出验证目标类不存在。 | 为 Mermaid 保留明确语言标记，或在引擎中单独处理；验证真正产生 SVG 图表。 |

**文件与导出：P2**

| 问题 | 位置和复现证据 | 修复方向 |
| --- | --- | --- |
| PDF 入口立即抛异常，完成状态契约也不正确 | exporter.py:50 调用不存在的 QWebEnginePage.layout；真实 QWebEnginePage 验证得到 AttributeError。53–54 又把异步 printToPdf 的 None 返回值转为 False。main_window.py:585–586 调用该入口。 | 使用 QPageLayout/QPageSize，等待 pdfPrintingFinished 或回调并显示失败原因；另验证全文打印和虚拟化的兼容性。 |
| 文档首次保存、另存为和导出缺少资源基准管理 | image_service.py:45、72；editor_session.py:174–180；exporter.py:29、46、92、99。临时目录验证：无标题文档插图落盘到 cwd/assets，保存到 notes/saved.md 成功但 notes/assets 图片不存在；HTML 导出到 exports 后仍使用 assets/original.png，目标目录也无图片。图片导出以临时 HTML 所在目录解析同样的相对地址。 | 导入前确定文档位置或使用受控暂存；保存位置改变时迁移资源或重写引用。导出显式传入 doc_base，复制/嵌入资源并生成可移植路径。 |
| 配置文档目录之外的相对图片目录时，先复制再报错 | image_service.py:46–53、72。实测 folder="../shared" 已成功复制图片，随后 relative_to(doc_dir) 抛 ValueError，没有返回引用。 | 先验证配置；若支持上级或绝对资源目录，用 relpath 生成相对引用，失败时清理本次创建的文件并提示。 |
| Pandoc 固定输出文件且在 GUI 线程阻塞 | exporter.py:66–72；main_window.py:601–607。实际调用 mock 捕获输出始终为 export-output.docx 等当前目录文件，没有目标选择，可能覆盖旧导出；同步 subprocess.run 最长等待 120 秒。 | 先让用户选择目标，确认覆盖，使用异步进程并提供进度/取消；传文档资源目录。未实际调用外部 Pandoc。 |
| 图片导出残留完整文档，缺少超时和媒体就绪判断 | exporter.py:92–118。固定 mdnote-capture.html 写入系统临时目录后不清理；加载和高度查询的事件循环都没有超时，loadFinished 的成功标志被忽略，仅固定等待 450ms。独立 HTML 未包含 KaTeX/Mermaid 运行资源。 | 使用独立临时目录并 finally 清理；处理加载失败、超时、关闭；等待图片解码/字体/图表完成，保证公式与图表导出一致。此项来自代码检查，未将真实长图导出判为通过。 |

**更新、设置和交付：P2**

| 问题 | 位置和复现证据 | 修复方向 |
| --- | --- | --- |
| 手动检查更新和下载进度使用不存在的 _stats | main_window.py:638、666。类无该成员，默认更新地址非空。抽取真实方法验证两条路径均抛 AttributeError；手动检查甚至未发请求。 | 从当前会话取 stats，覆盖无标签、检查中、下载中、失败状态。 |
| 设置更新源后运行中的服务仍使用旧地址 | main_window.py:61–64、269–286。UpdateManager 只在构造时读地址，设置通知不更新它。 | 将更新服务纳入设置变更处理，明确正在进行的请求如何取消或继续。 |
| 重复下载的旧回调读取并结束新请求 | updater.py:140–159、165–199。fake reply 验证连调两次 download 后，旧 readyRead 读取新 reply；旧 finished 在新下载未完成时发送 download_finished 并释放新 reply。旧临时流及路径丢失。 | 拒绝重复下载或按请求持有独立状态，绑定回调的 reply 和发布信息，管理取消与清理。 |
| 下载写入失败可能仍报告成功 | updater.py:158、165–199。mock write 抛磁盘满后，无 SHA 路径仍发成功信号，失败信号为空。 | 记录写入异常、终止请求并清理；完成前必须确认文件成功关闭、写入长度及摘要。 |
| 带查询参数的下载 URL 无法正确创建 Windows 临时文件 | updater.py:143–146。Path(url).suffix 将 .exe?sig=123 当后缀，包含 Windows 禁止的问号，且 mkstemp 异常未处理。 | 只解析 URL 的 path，固定/白名单后缀，捕获临时文件创建失败。 |
| 静默更新不恢复自定义安装目录，也没有关闭旧实例 | main_window.py:674–679；setup.nsi:15、71。仅传 /S；完整 NSIS 脚本未读取 InstallLocation，也未实现关闭/等待实例的逻辑。 | 读取已安装位置或明确传入安装目录；退出旧进程后执行升级，验证文件占用和升级失败恢复。实际安装更新未执行。 |
| 设置落盘失败后内存和界面状态分裂 | settings.py:83–88。patch 先修改 current，save 失败时未回滚也未通知。模拟 OSError 后内存 theme 已改变，监听器未调用。设置弹窗、F8/F9 等调用处缺少失败提示处理。 | 在副本上修改，成功保存后再替换 current 和通知；失败保留原状态，并给出可恢复反馈。 |

**性能与架构：P2**

单块提交仍会重建全文模型和全部渲染 payload。webview.py:80 的 LRU 只有 512 项，90–123 顺序遍历全文；超过缓存容量的不同块导致重复整轮失效。commit:225、transform:251/269 在 QWebChannel 主线程生成负载，浏览器 DOM 窗口化没有减少这部分 Python 工作。

本机独立 Python 测量，使用不同内容的段落，修改第一块后记录一次提交；这些数值是本机样本，不是跨硬件基准：

| 段落数 | 字符数 | 首次 payload | 单块修改 commit | commit 缓存命中 |
| ---: | ---: | ---: | ---: | --- |
| 1,000 | 51,888 | 369 ms | 314 ms | 0 hit / 1,000 miss |
| 3,000 | 157,888 | 898 ms | 951 ms | 0 hit / 3,000 miss |

建议保留按稳定块标识保存的渲染结果，只计算修改块及受影响结构；页面接收增量更新；对必须全量计算的工作明确线程归属并避免跨线程共享非线程安全引擎。增加“单块提交工作量不随全文块数线性增长”的性能验证。

打开/保存时更新最近文件，也会触发主题和所有标签偏好刷新：main_window.py:182、269–274 → SourceEditor.apply_theme → md_highlighter.py:111 的 rehighlight。10 标签 fake 验证仅 recent_files 变化就触发 1 次外壳刷新、10 次编辑器刷新。建议设置通知携带变更字段；最近文件仅刷新菜单，主题或字体变化才刷新编辑器。

**较低优先级的一致性问题**

- mermaid、code_line_numbers 设置仅被设置存储和弹窗读写，渲染端没有消费；app.js 的 Mermaid 路径无条件处理，Markdown 引擎未配置代码行号。应实现这些偏好，或去掉无效选项与对应功能承诺。
- installer/setup.nsi:65 的 DisplayVersion 固定 0.1.0，源码及 latest.json 为 0.2.0。发布版本应集中定义并在构建时注入。

**条件安全风险与待验证事项**

- 更新清单仅要求 version 和 url；updater.py:45–55、185 接受 HTTP/file URL 与空 SHA。自定义 HTTP 清单，或清单提供 HTTP 安装包并省略摘要时，传输内容可能被篡改后进入可执行文件启动流程。默认仓库 latest.json 使用 HTTPS 且包含 SHA，不能据此称默认路径已遭篡改。建议验证协议、摘要格式及必要字段；摘要不能替代清单来源的信任验证。
- setup.nsi:16 要求管理员权限，而 main_window.py:679 用 subprocess.Popen 启动安装器；普通权限安装环境中的提权与可能的 WinError 740 需 Windows 实机验证。
- 超过 400 块时 app.js:367 将远处 DOM 清空，而 editor_session.py 的渲染查找调用原生 findText；远处全文查找、目录跳转及修复后的 PDF 全文输出应专门验证。本轮未完成这些真实浏览器场景，不列为已复现缺陷。
- 未进行依赖漏洞数据库扫描、更新服务真实网络测试或已打包二进制验收；不对这些未检验范围作安全或交付保证。

**验证结果与后续验收**

- 隔离用户设置、禁用自动联网更新，以 QT_QPA_PLATFORM=offscreen 和 QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu 执行完整 unittest discover：66 项，65 通过，1 跳过，用时 26.746 秒。跳过项为目录符号链接环境不支持（tests/test_reliability.py:63）。
- 独立编辑纯函数脚本：33 项通过；unittest 导入阶段另运行插件脚本 8 项及搜索服务脚本 11 项，均通过。这些结果分开统计。
- node --check mdnote/editor/web/app.js 通过；git diff --check 通过，仅有现有 LF/CRLF 提示。
- 使用真实 QWebEnginePage 复现 PDF API 错误；使用真实保存方法和临时目录验证图片路径；其他重点结论由实际方法、原始 JS 函数、受控 mock 和静态路径检查组合支持。
- 离屏 Qt 产生 GPU/GLES 日志；测试退出码为 0。表格代理进程的浏览器初始化回调超时，因此未把表格真实 GUI 交互标为通过。
- 本轮只新增这份报告；此前源码变更保留，安装包与 dist 没有重建。

建议按以下顺序补充有意义的验收：先做多标签外部冲突、表格无修改往返、卸载保留用户文件和故障插件恢复；再做含图片/公式/图表的完整导出、更新请求失败与重入、设置落盘失败；最后验证 1,000/3,000 块文档提交耗时、全范围查找和两个模式的逻辑行定位。
