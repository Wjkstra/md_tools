# 性能设计：长文档低负载

本文汇总 MdNote 在性能方面的设计：视口虚拟化、高度校正、动态加载、
多层缓存、防抖节流与内存泄漏防护，以及实测基准数据。

## 1. 性能目标与负载来源

| 目标 | 指标 |
| --- | --- |
| DOM 规模与文档长度解耦 | 挂载节点数恒定（只与视口高度有关） |
| 打开 / 装载迅速 | 6 万块文档解析 + 首屏 < 1.5s |
| 滚动顺滑 | 无整页重排；滚动中仅做区间增删行 |
| 内存可控 | 缓存全部定容；卸载即释放，长期使用不膨胀 |

长文档的四类负载来源及对策：

| 负载来源 | 对策 |
| --- | --- |
| DOM 节点过多 → 布局 / 内存压力 | **视口虚拟化**，只挂载可见块 |
| 重型库（Mermaid、highlight.js 全量语言） | **动态 import**，按需加载、按类型分包 |
| 重复渲染相同内容 | **LRU 渲染缓存** + 内容哈希 id |
| 高频事件（输入、滚动、文件变更） | **rAF / 防抖**，异步结果带代次与取消信号 |

## 2. 视口虚拟化

核心实现在 `editor/virtual-list.ts`。

### 2.1 结构

```
editor-scroll（滚动容器，position: relative）
└── vl-spacer（高度 = 全部块高度之和，撑出正确滚动条）
    └── vl-row × N（position:absolute; transform: translate3d(0, y, 0)）
        └── 块内容
```

### 2.2 挂载区间

滚动 / resize 事件经 **requestAnimationFrame 合并**后：

```
top    = scrollTop - overscan(400px)
bottom = scrollTop + clientHeight + overscan(400px)
index  = pos[] 前缀和上二分查找
```

- 区间外的行：`unobserve → 行级 Lifetime dispose → DOM 移除`
- 区间内未挂载的行：`translate3d 定位 → 填充 HTML → observe`

挂载行数只取决于视口高度，**与文档总块数无关**。

### 2.3 为什么用 transform 而不是 top

- `translate3d` 触发 GPU 合成层，行平移不引发布局（layout）
- 行离开 / 进入窗口时只动受影响的行，文档其余部分零成本

## 3. 高度估算与实测校正

新文档在首帧渲染前没有真实高度。采用**估算 → 实测 → 增量校正**：

1. `estimateHeight(block)`：按块类型与行数给出占位高度（见下表）
2. 行挂载后 `ResizeObserver` 立即回传真实高度
3. `applyHeight()` 做增量修正：

```
delta = 实测 - 估算
pos[k] += delta     （k > index 的前缀和全部平移）
总高 += delta
```

### 滚动稳定：视口上方变化反向补偿

若高度变化的行位于当前挂载区间**上方**，同步执行
`scrollTop += delta`——内容变高多少、滚动位置就补偿多少，
用户眼中的内容完全不跳。视口下方的变化（如图片异步加载完撑开）
只影响后续行，不移动当前视野。

### 估算规则（初始占位）

| 块类型 | 估算 |
| --- | --- |
| heading 1–3 / 4–6 | 52 / 44 px |
| hr | 34 px |
| toc | 180 px |
| code / frontmatter | 行数 × 22 + 34 |
| math / html | 行数 × 26 + 24 / × 22 + 16 |
| blockquote / list | 行数 × 30 + 18 / × 32 + 14 |
| table | 行数 × 34 + 18 |
| paragraph | max(1, ⌈字符数 / 46⌉) × 28 + 16 |

实测高度按块内容哈希缓存，文档结构重建后命中，避免反复校正。

## 4. 动态加载策略

重型依赖**不进入首屏包**，首次使用时才加载：

| 资源 | 加载时机 | 分包效果 |
| --- | --- | --- |
| highlight.js 全量语言包 | 应用启动后后台预热（不阻塞首屏），首次渲染代码块时可用 | 单包动态加载 |
| Mermaid 核心 | 首次渲染 Mermaid 块 | 独立 chunk（~1.1MB 独立） |
| Mermaid 各图表类型 | 渲染对应类型时（flow / sequence / gantt / pie / c4 / er / git / xychart…） | 每类独立 chunk，用到才下载/解析 |

效果：日常纯文本写作永远不付出图表库的内存与解析成本。

## 5. 多层缓存

| 缓存 | 位置 | 容量 | 失效方式 |
| --- | --- | --- | --- |
| 块渲染 HTML | BlockViewFactory 的 `LRU` | 300 | 文本变化（块 id 改变）自然不命中；外观变化整体清空 |
| 块实测高度 | VirtualList `measured` Map | 超 2000 时清理不存在的旧块 | 内容哈希变化 |
| 语法高亮 | 随块 HTML 缓存 | 同上 | 同上 |

所有缓存都是**有界**的：LRU 超容量淘汰最旧项；Map 超限按存活块集合裁剪。
不存在随文档长度无限增长的容器。

## 6. 防抖与节流

| 场景 | 策略 | 时延 |
| --- | --- | --- |
| 滚动 / resize 重算挂载区间 | rAF 合并 | 每帧最多一次 |
| 字数统计 | debounce | 200ms |
| 大纲更新 | debounce | 300ms |
| 自动保存 | debounce | 1000ms |
| 文件树刷新（外部变更） | debounce | 250ms |
| 文件监视器事件 | 主进程 150ms 合并 + 同路径去重 | — |
| 大纲当前章节（滚动） | debounce | 120ms |

## 7. 异步结果安全（防竞态）

块卸载后其异步任务（Mermaid 渲染等）可能才返回，若直接写 DOM 就是泄漏 / 错位：

- 每行的异步任务传入行级 `AbortSignal`，挂载新结果前检查 `signal.aborted`
- Mermaid 渲染生成的临时容器在完成后显式移除
- 这类「过期结果」一律丢弃，不允许触碰已卸载的 DOM

## 8. 内存泄漏防护清单

| 资源 | 管理方式 |
| --- | --- |
| DOM 事件监听 | `Lifetime.on` 基于 AbortSignal，dispose 一次性移除 |
| ResizeObserver | 行卸载即 `unobserve`；VirtualList 销毁时 `disconnect` |
| 定时器 | `Lifetime.timeout/interval`，dispose 清理 |
| 文件监视器 | 每文件夹单句柄；切换 / 关闭文件夹时 `watcher.close()`，并清理合并计时器 |
| 行级控制器（表格等） | 存活于行级 Lifetime，行卸载即失效；编辑会话监听用独立 AbortController |
| 外部插件 | URL.createObjectURL 加载后立即 revoke；deactivate 在卸载时调用 |
| 导出离屏窗口 | finally 中 destroy + 删除临时 HTML |
| Blob URL | 统一在 import 完成 / finally 中 revoke |

## 9. 基准数据（自动化冒烟实测）

测试机：Windows 10，Node 24。通过 SMOKE 模式自动驱动：

### 60,000 块文档（30,000 标题 + 30,000 段落，总高约 2,880,706 px）

| 指标 | 实测 |
| --- | --- |
| 解析 + 装载耗时 | **≈ 1.3s** |
| 顶部挂载行数 | 26 |
| 中部挂载行数 | 35 |
| 底部挂载行数 | 25 |
| 滚动时挂载行数波动 | 25 ~ 35（恒定为小常数） |

### 功能夹具（16 块、含表格 / 代码 / 图表 / 公式）

- 视口 + overscan 覆盖的块即时挂载，其余滚到才挂载
- 编辑提交后内容正确持久化，无渲染进程错误

### 复现方法

```bash
npm run build
SMOKE=1 npx electron .     # Windows PowerShell: $env:SMOKE=1; npx electron .
```

## 10. 贡献者性能准则

- 任何「整篇文档」级别的循环都要问：能否只做变化的块 / 视口内的块？
- 新缓存**必须定容**；新监听**必须**登记 Lifetime
- 新异步任务必须接受 AbortSignal 并在写 DOM 前检查
- 块内避免创建长期存活的全局对象；跨块状态归 App / 服务层
- 图片 / 媒体一律加 `loading="lazy"`、`decoding="async"`

## 11. 相关文档

- [架构设计](architecture.md)：VirtualList 在分层中的位置
- [数据模型](data-model.md)：块高度与哈希的定义
- [安全模型](security.md)：异步加载与 CSP 的约束
