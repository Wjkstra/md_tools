# 数据模型：块级文档模型

本文描述 MdNote 的核心数据结构——**块级文档模型（Block Document Model）**：
它如何切分 Markdown、如何保证可逆，以及编辑变换如何作用于它。

## 1. 为什么需要块模型

「实时渲染 + 单块编辑 + 长文档虚拟化」要求文档具备结构化索引：

- 点击某块时，只需显示 / 提交**这一块**，不触碰整篇 HTML
- 虚拟化需要知道「第 N 块的位置和高度」才能只挂载可见区域
- 撤销重做需要精确到字符偏移的 splice 记录

但 Markdown 是纯文本。MdNote 的做法是：**规范文本（canonical text）是唯一事实源，
块模型是它的可重建派生物**，二者严格双向可逆。

## 2. 模型结构

```typescript
interface DocModel {
  text: string              // 规范文本（= 原文）
  blocks: Block[]           // 有序块列表
  gaps: number[]           // 每个块内容之后的换行数（含块间与文末）
}

interface Block {
  id: string                // type|lang|raw 内容的 FNV-1a 哈希
  type: BlockType
  start: number             // 内容起始偏移（含）
  end: number               // 内容结束偏移（不含尾随换行）
  raw: string               // 块原文 = text.slice(start, end)
  lang?: string             // 代码块语言
  level?: number            // 标题级别 1~6
}
```

### 块类型

| BlockType | 识别规则 | 渲染方式 |
| --- | --- | --- |
| `frontmatter` | 文档起始 `---`，闭合于 `---` 或 `...`（遇空行失效） | YAML 解析为键值表 |
| `code` | 围栏 ```` ``` ```` 或 `~~~`（允许 0–3 空格缩进），闭合符同字符且长度不小于起始符 | 语言标识 → highlight.js；`mermaid` 走图表渲染 |
| `math` | 独立行 `$$` 配对，或单行 `$$...$$` | KaTeX displayMode |
| `heading` | ATX 风格 `#{1,6}` | 标题 + slug id |
| `blockquote` | 行首 `>`（允许空行后继续） | markdown-it 引用 |
| `list` | `-` / `+` / `*` / `数字.` / `数字)`；含缩进续行与松散列表 | markdown-it 列表；`- [ ]` 识别为任务项 |
| `table` | 含 `\|` 的行 + 下一行是分隔行 `:?--` | 表格 + TableController |
| `hr` | `---` / `***` / `___`（或三个带空格的标记） | `<hr>` |
| `toc` | 独立 `[toc]`（大小写不敏感） | 从标题派生的目录 |
| `html` | 标签 / `<!--` / `<!DOCTYPE` / `<?` 起始，吃到空行 | 净化后输出 |
| `paragraph` | 其余情况，吃到空行或新块起点 | markdown-it 段落 |

解析优先级（自上而下匹配）：frontmatter → code → math → hr → toc → heading
→ blockquote → list → table → html → paragraph。

## 3. 解析算法

`buildModel(text)` 是**纯函数**，分两步：

### 3.1 行切分

一次扫描记录每行的起始偏移与去 `\r` 文本：

```
lineStarts[i] = 第 i 行第一个字符在 text 中的偏移
lineTexts[i]  = 第 i 行文本（不含 \n，去掉行尾 \r）
```

### 3.2 范围归并

游标 `cursor` 逐行推进，按上表规则识别块、吃掉属于该块的所有行
（多行块 = 一个范围 `[a, b)`），跳过空行。最后把行范围换算成字符偏移：

```
start = lineStarts[a]
end   = lineStarts[b-1] + lineTexts[b-1].length
raw   = text.slice(start, end)
```

### 空文档

没有任何块时生成一个 `paragraph` 空块，保证编辑器始终有可点击的块。

## 4. 偏移与间隙不变量

块的 `start/end` 只覆盖**内容行**；块与块之间的换行不计入任何块，
由 `gaps[i]` 单独记录。三条核心不变量：

1. **覆盖不变量**：拼接结果恒等于原文

$$
\text{text} = \sum_{i} \left( \text{blocks}[i].raw + \texttt{'\n'}^{\,gaps[i]} \right)
$$

2. **顺序不变量**：`blocks` 按 `start` 严格升序，块区间互不重叠
3. **自洽不变量**：`block.raw === text.slice(block.start, block.end)`

`serialize(model)` 依据不变量 1 重建文本，与原文逐字节一致——
这是「编辑可逆」的数学保证，且有对应测试（编辑提交后内容持久化校验）。

### 为什么 gaps 要独立存在

考虑：

```markdown
第一段

第二段
```

若把尾随换行并入块 raw，段落块在「一个 / 两个 / 零个换行」三种排版下
raw 都不同，缓存与 diff 全部失效。gaps 独立后：**内容变化与间距变化解耦**，
块渲染缓存按 raw 哈希命中，行高测量与间距互不干扰。

## 5. 标题与大纲

`extractHeadings(model)` 扫描 heading 块：

- 去除前缀 `#`、尾部闭合 `#` 与内联标记（`*_\`~`）
- `slugify()` 生成锚点 id：小写、去标点、空白转 `-`
- 重名自动追加 `-2`、`-3`…，保证 id 唯一

大纲、`[toc]` 块、导出目录、滚动当前章节全部消费同一份标题列表。

## 6. 编辑变换

编辑动作不直接操作 DOM，而是生成 `{text, caret}` 的**纯函数结果**，
由 LiveEditor 统一转成规范文本上的 splice：

| 变换 | 触发 | 行为 |
| --- | --- | --- |
| `splitAt` | Enter | 列表：插入延续标记（有序列表自动 +1）；空列表项回车 → 降级为段落；引用：插入 `> `；标题：新建段落；其他：朴素换行 |
| `mergeWith` | 行首 Backspace | 与上一块合并，光标落在接缝处 |
| `indentLine` | Tab / Shift+Tab（列表中） | 行首增删缩进（Tab 宽度取设置） |
| `detectSpaceTrigger` | 输入空格 | 检测 `# `、`> `、`- `、`1. `、`- [ ] `、```` ``` ````、`$$` 等前缀，即时展开对应结构 |
| `wrapSelection` | Ctrl+B/I 等 | 用成对标记包裹选区；无选区时插入标记对 + 占位符并选中占位符 |
| `insertAt` | 图片 / 链接 / 拖放 | 在偏移处插入字符串 |

每次提交对应规范文本上的一条 splice：

```typescript
{ start, before: text.slice(start, end), after: insert, caret }
```

记录进 `EditHistory`（容量 300）即可支持跨块撤销 / 重做，
撤销时反向应用同一条记录，无需为历史保存整篇文档。

## 7. 块标识与缓存

块 id = FNV-1a(`type|lang|raw`)。内容未变的块：

- 渲染 HTML 缓存命中（LRU，容量 300）
- 实测高度缓存命中（避免重新估算）
- 结构重建时滚动锚点可以按 id 找到同一块

任何字符修改都会改变 id，天然防止「显示了旧块的缓存」类问题。

## 8. 扩展块类型

新增一种块（如脚注块、定义列表块）的步骤：

1. `BlockType` 联合类型增加成员
2. 在 `buildModel` 的游标循环中、**paragraph 兜底之前**加入识别规则并给出范围
3. 在 `estimateHeight` 中给出占位行高
4. 在 `BlockViewFactory.build` 中生成展示 HTML（必须经 `sanitizeHtml`）
5. 需要交互时在 `postProcess` 中绑定控制器，监听一律登记到行级 Lifetime

## 9. 相关文档

- [架构设计](architecture.md)：块模型在整体架构中的位置
- [性能设计](performance.md)：块缓存与高度测量
- [插件开发](plugin-development.md)：通过插件扩展 Markdown 语法而无需改模型
