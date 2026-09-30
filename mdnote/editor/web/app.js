// 实时模式前端控制器：块渲染 / 点击编辑 / 按键经 QWebChannel 交给 Python 计算。
"use strict";

const App = {
  blocks: [],
  editingIndex: -1,
  bridge: null,
  pendingTransform: false,
  pendingInput: [],
  activeIndex: 0,
  lastCaret: 0,
  epoch: 0,
  requestSerial: 0,
  verticalX: null,

  // 超长文档的按需排版（窗口化）
  WINDOW_THRESHOLD: 400,   // 块数超过该值才启用窗口化
  VIEWPORT_PAD: 1200,      // 视口上下额外排版的像素余量
  measuredHeights: new Map(),  // 块索引 -> 实测内容高度
  mountedRange: [0, 0],
  _viewportQueued: false,

  init(bridge) {
    this.bridge = bridge;
    document.addEventListener("mousedown", (e) => this.onMouseDown(e), true);
    document.addEventListener("keydown", (e) => this.onKeyDown(e));
    document.addEventListener(
      "scroll", () => this.scheduleViewportUpdate(), true
    );
    window.addEventListener("resize", () => this.scheduleViewportUpdate());
    document.addEventListener("input", () => this.syncDraft());
    document.addEventListener("beforeinput", (e) => {
      if (!this.pendingTransform || !e.cancelable) return;
      const commands = {insertText: "insertText", deleteContentBackward: "delete",
        deleteContentForward: "forwardDelete"};
      const command = commands[e.inputType];
      if (!command) return;
      e.preventDefault();
      this.pendingInput.push(() => document.execCommand(command, false, e.data || ""));
    });
    // 链接：页内锚点（#id / TOC）就地滚动；其余（外部网址）交系统浏览器
    document.addEventListener("click", (e) => {
      const a = e.target.closest("a");
      if (!a || a.classList.contains("toc-link")) return;
      const href = a.getAttribute("href");
      if (href && href.charAt(0) === "#") return; // 页内锚点，默认滚动
      e.preventDefault();
      if (href) bridge.openExternal(href);
    });
    this.bindMedia();
    const doc = document.getElementById("doc");
    doc.tabIndex = 0;
    doc.setAttribute("role", "document");
    doc.setAttribute("aria-label", "Markdown 文档编辑区");
    bridge.loadBlocks((s) => { this.renderAll(JSON.parse(s)); this.focusEditor(); });
  },

  // ---------------- 图片拖放 / 粘贴 ----------------

  bindMedia() {
    document.addEventListener("dragover", (e) => {
      if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) e.preventDefault();
    });
    document.addEventListener("drop", (e) => this.onMedia(e, e.dataTransfer));
    document.addEventListener("paste", (e) => {
      if (e.clipboardData && e.clipboardData.files.length) {
        this.onMedia(e, e.clipboardData);
      } else if (this.editingIndex >= 0 && e.clipboardData) {
        e.preventDefault();
        const text = e.clipboardData.getData("text/plain").replace(/\r\n?/g, "\n");
        const insert = () => this.replaceSelection(text);
        if (this.pendingTransform) this.pendingInput.push(insert);
        else insert();
      }
    });
  },

  async onMedia(event, transfer) {
    if (!transfer || !transfer.files || transfer.files.length === 0) return;
    const files = [...transfer.files].filter((f) => f.type.startsWith("image/"));
    if (!files.length) return;
    event.preventDefault();
    const mds = [];
    for (const file of files) {
      let dataUrl;
      try {
        dataUrl = await this.readAsDataURL(file);
      } catch {
        continue;
      }
      const md = await new Promise((r) =>
        this.bridge.addImage(
          JSON.stringify({ dataUrl, fileName: file.name || null }), r
        )
      );
      mds.push(md);
    }
    if (mds.length) this.insertMedia(mds.join("\n"));
  },

  readAsDataURL(file) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(fr.result);
      fr.onerror = reject;
      fr.readAsDataURL(file);
    });
  },

  insertMedia(md) {
    if (this.editingIndex >= 0) {
      const el = document.querySelector(".block.is-editing");
      const sel = getSelection();
      const off = this.textOffset(el, sel.anchorNode, sel.anchorOffset);
      const text = el.textContent;
      el.textContent = text.slice(0, off) + md + text.slice(off);
      this.setCaret(el, off + md.length);
      this.syncDraft();
    } else {
      // 未在编辑：落到文档末尾挂尾块
      const lastIndex = this.blocks.length - 1;
      this.bridge.commit(lastIndex, md, (s) => this.renderAll(JSON.parse(s)));
    }
  },

  // ---------------- 可视化表格编辑 ----------------

  attachTableEditor(blockEl, index, target) {
    const table = blockEl.querySelector("table");
    if (!table) return;
      for (const cell of table.querySelectorAll("th,td")) {
        if (cell.dataset.bound) continue;
        cell.dataset.bound = "1";
        cell.setAttribute("tabindex", "-1");
        cell.addEventListener("click", () => this.editCell(cell, table, index));
        cell.addEventListener("input", () => this.submitTable(table, index));
        cell.addEventListener("keydown", (e) => {
          if (e.isComposing || e.keyCode === 229) return;
          if (this.pendingTransform) return; // document handler queues the event
          if (e.key === "F2" || ((e.ctrlKey || e.metaKey) && e.key !== "Enter")) return;
          const cells = [...table.querySelectorAll("th,td")];
          const i = cells.indexOf(cell);
          const cols = table.rows[0].cells.length;
          let next = null;
          if (e.key === "Escape") {
            e.preventDefault(); e.stopPropagation(); cell.blur(); this.focusBlock(index); return;
          }
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault(); e.stopPropagation(); this.switchTo(index + 1, {caret:0}); return;
          }
          if (e.key === "Tab") next = i + (e.shiftKey ? -1 : 1);
          else if (e.key === "Enter") next = i + (e.shiftKey ? -cols : cols);
          else if (!e.shiftKey && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
            const selection = this.selectionOffsets(cell);
            if (!selection || selection[0] !== selection[1]) return;
            const offset = selection[0];
            if (e.key === "ArrowLeft" && offset === 0) next = i - 1;
            if (e.key === "ArrowRight" && offset === cell.textContent.length) next = i + 1;
            if (["ArrowUp", "ArrowDown"].includes(e.key)) {
              const rect = this.caretRect(cell, offset);
              const edge = this.caretRect(cell, e.key === "ArrowUp" ? 0 : cell.textContent.length);
              if (Math.abs(rect.top - edge.top) < Math.max(2, rect.height / 2)) next = i + (e.key === "ArrowUp" ? -cols : cols);
            }
          }
          if (next === null) return;
          e.preventDefault(); e.stopPropagation();
          if (next >= cells.length && ["Tab", "Enter"].includes(e.key)) {
            this.appendTableRow(table);
            this.attachTableEditor(blockEl, index, table.querySelectorAll("th,td")[next]);
            this.submitTable(table, index);
          } else if (next < 0 || next >= cells.length) {
            this.switchTo(index + (next < 0 ? -1 : 1), {caret:next < 0 ? "end" : 0, cell:next < 0 ? -1 : 0});
          } else this.editCell(cells[next], table, index);
        });
        cell.addEventListener("blur", () => {
          if (cell.isContentEditable) {
            cell.contentEditable = "false";
            this.submitTable(table, index); // 静默回写，不打断连续编辑
          }
        });
      }
    const cell = target.closest("th,td");
    if (cell) this.editCell(cell, table, index);
  },

  editCell(cell, table, index) {
    cell.contentEditable = "true";
    cell.setAttribute("role", "textbox");
    cell.focus({preventScroll:true});
    this.activeIndex = index;
    this.tableCellIndex = [...table.querySelectorAll("th,td")].indexOf(cell);
    this.markActive(index);
    this.setCaret(cell, cell.textContent.length);
  },

  appendTableRow(table) {
    const row = document.createElement("tr");
    for (const header of table.rows[0].cells) {
      const cell = document.createElement("td");
      cell.style.textAlign = header.style.textAlign;
      row.appendChild(cell);
    }
    (table.tBodies[0] || table).appendChild(row);
    return row;
  },

  tableCommand(command) {
    if (this.pendingTransform) { this.pendingInput.push(() => this.tableCommand(command)); return; }
    const block = document.querySelector(`.block[data-index="${this.activeIndex}"]`);
    const table = block && block.querySelector("table");
    if (!table) return;
    const cells = [...table.querySelectorAll("th,td")];
    let cell = cells[Math.min(this.tableCellIndex || 0, cells.length - 1)];
    const row = cell.parentElement;
    const col = cell.cellIndex;
    if (command === "row") {
      const added = this.appendTableRow(table);
      if (row.parentElement.tagName !== "THEAD") row.after(added);
      cell = added.cells[col];
    } else if (command === "column") {
      for (const r of table.rows) {
        const added = document.createElement(r.cells[col].tagName);
        r.cells[col].after(added);
        if (r === row) cell = added;
      }
    } else if (command === "deleteRow") {
      if (row.rowIndex === 0) return; // Preserve the header required by Markdown tables.
      cell = table.rows[row.rowIndex - 1].cells[col];
      row.remove();
    } else if (command === "deleteColumn") {
      if (row.cells.length <= 1) return;
      for (const r of table.rows) r.cells[col].remove();
      cell = row.cells[Math.min(col, row.cells.length - 1)];
    } else if (["left", "center", "right"].includes(command)) {
      for (const r of table.rows) r.cells[col].style.textAlign = command;
    }
    this.attachTableEditor(block, this.activeIndex, cell);
    this.submitTable(table, this.activeIndex);
  },

  submitTable(table, index) {
    if (this.pendingTransform) { this.pendingInput.push(() => this.submitTable(table, index)); return; }
    if (!table.isConnected) return;
    const md = this.tableToMarkdown(table);
    if (this.blocks[index].raw === md) return;
    this.runBridge("updateTable", [index, md], (blocks) => { this.blocks = blocks; });
  },

  tableToMarkdown(table) {
    const rows = [...table.querySelectorAll("tr")];
    const lines = rows.map((tr) => {
      const cells = [...tr.querySelectorAll("th,td")];
      const parts = cells.map((c) => {
        const t = c.textContent.replace(/\|/g, "\\|").trim();
        return t === "" ? " " : t;
      });
      return "| " + parts.join(" | ") + " |";
    });
    if (lines.length) {
      const markers = [...rows[0].querySelectorAll("th,td")].map((cell) => {
        const align = cell.style.textAlign || cell.getAttribute("align");
        return align === "center" ? ":---:" : align === "right" ? "---:" :
          align === "left" ? ":---" : "---";
      });
      lines.splice(1, 0, "| " + markers.join(" | ") + " |");
    }
    return lines.join("\n");
  },

  // ---------------- 渲染 ----------------

  get windowed() {
    return this.blocks.length > this.WINDOW_THRESHOLD;
  },

  blockHeight(index) {
    const cached = this.measuredHeights.get(index);
    if (cached) return cached;
    const b = this.blocks[index];
    if (!b) return 30;
    const lines = Math.max(1, Math.ceil(b.raw.length / 56));
    const perType = {
      heading: 52, hr: 34, code: lines * 22 + 24,
      math: lines * 26 + 20, list: lines * 30 + 16,
      blockquote: lines * 30 + 16, table: lines * 34 + 18,
      paragraph: lines * 27 + 12,
    };
    return perType[b.type] || 30;
  },

  computeMountedRange() {
    const scrollY = window.scrollY || 0;
    const viewH = window.innerHeight || 600;
    const top = scrollY - this.VIEWPORT_PAD;
    const bottom = scrollY + viewH + this.VIEWPORT_PAD;
    let acc = 0;
    let start = 0;
    let startSet = false;
    let end = this.blocks.length;
    for (let i = 0; i < this.blocks.length; i++) {
      const h = this.blockHeight(i);
      if (!startSet && acc + h >= top) {
        start = i;
        startSet = true;
      }
      if (startSet && acc >= bottom) {
        end = i;
        break;
      }
      acc += h;
    }
    return [start, end];
  },

  isMounted(index) {
    const [s, e] = this.mountedRange;
    return index >= s && index < e;
  },

  scheduleViewportUpdate() {
    if (this._viewportQueued || !this.windowed) return;
    this._viewportQueued = true;
    requestAnimationFrame(() => {
      this._viewportQueued = false;
      this.updateViewport();
    });
  },

  updateViewport() {
    const next = this.computeMountedRange();
    const [prevS, prevE] = this.mountedRange;
    this.mountedRange = next;
    const [s, e] = next;
    for (let i = s; i < e; i++) {
      if (i >= prevS && i < prevE) continue;
      this.mountBlock(i);
    }
    for (let i = prevS; i < prevE; i++) {
      if (i >= s && i < e) continue;
      if (i === this.editingIndex) continue;
      this.unmountBlock(i);
    }
  },

  mountBlock(index) {
    const b = this.blocks[index];
    const el = document.querySelector(`.block[data-index="${index}"]`);
    if (!el || !b) return;
    const before = el.getBoundingClientRect();
    el.classList.remove("block-placeholder");
    el.style.minHeight = "";
    el.innerHTML = b.html;
    const measured = el.getBoundingClientRect().height;
    if (measured > 0) this.measuredHeights.set(index, measured);
    this.postProcessBlock(el);
    const after = el.getBoundingClientRect();
    const delta = after.top - before.top;
    if (delta && index <= this.mountedRange[0]) window.scrollBy(0, delta);
  },

  unmountBlock(index) {
    const el = document.querySelector(`.block[data-index="${index}"]`);
    if (!el) return;
    const h = this.blockHeight(index);
    el.classList.add("block-placeholder");
    el.style.minHeight = `${h}px`;
    el.innerHTML = "";
  },

  measureMountedAndRefine() {
    const [s, e] = this.mountedRange;
    for (let i = s; i < e; i++) {
      const el = document.querySelector(`.block[data-index="${i}"]`);
      if (el && !el.classList.contains("block-placeholder")) {
        const h = el.getBoundingClientRect().height;
        if (h > 0) this.measuredHeights.set(i, h);
      }
    }
  },

  postProcessBlock(el) {
    if (window.katex) this.renderMathIn(el);
    const mermaidCode = el.querySelector("code.language-mermaid");
    if (mermaidCode) {
      const host = document.createElement("div");
      host.className = "mermaid";
      host.textContent = mermaidCode.textContent;
      (mermaidCode.closest(".codehilite") || mermaidCode).replaceWith(host);
      if (window.mermaid) {
        try {
          window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
          window.mermaid.run({ nodes: [host] });
        } catch (e) { /* ignore */ }
      }
    }
  },

  renderAll(blocks) {
    const previous = this.blocks;
    this.blocks = blocks;
    this.editingIndex = -1;
    const doc = document.getElementById("doc");
    const oldNodes = [...doc.children];
    const windowed = this.windowed;
    if (windowed) this.mountedRange = this.computeMountedRange();

    for (const b of blocks) {
      let el = oldNodes[b.index];
      const old = previous[b.index];
      const shouldMount = !windowed || this.isMounted(b.index);
      // Keep unchanged rendered nodes, including expensive diagrams and tables.
      if (el && !el.classList.contains("is-editing") && old &&
          old.raw === b.raw && old.html === b.html && old.type === b.type &&
          el.classList.contains("block-placeholder") === !shouldMount) continue;
      el = document.createElement("div");
      el.className = `block block-${b.type}`;
      el.dataset.index = String(b.index);
      el.tabIndex = -1;
      el.setAttribute("aria-label", `第 ${b.index + 1} 段，${b.type}`);
      if (b.trailing) el.classList.add("block-trailing");
      if (shouldMount) {
        el.innerHTML = b.html;
      } else {
        el.classList.add("block-placeholder");
        el.style.minHeight = `${this.blockHeight(b.index)}px`;
      }
      if (oldNodes[b.index]) oldNodes[b.index].replaceWith(el);
      else doc.appendChild(el);
    }
    oldNodes.slice(blocks.length).forEach((el) => el.remove());
    this.activeIndex = Math.min(this.activeIndex, blocks.length - 1);
    this.postProcess();
    if (windowed) this.measureMountedAndRefine();
  },

  postProcess() {
    // TOC 链接：滚动到对应标题
    for (const link of document.querySelectorAll(".toc-link")) {
      if (link.dataset.bound) continue;
      link.dataset.bound = "1";
      link.addEventListener("click", () => {
        const el = document.getElementById(link.dataset.tocId);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    for (const code of document.querySelectorAll("code.language-mermaid")) {
      const host = document.createElement("div");
      host.className = "mermaid";
      host.textContent = code.textContent;
      const wrap = code.closest(".codehilite") || code;
      wrap.replaceWith(host);
    }
    const nodes = document.querySelectorAll(".mermaid");
    if (nodes.length && window.mermaid) {
      try {
        window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
        window.mermaid.run({ nodes });
      } catch (e) {
        /* Mermaid 初始化失败：忽略，保持原始文本 */
      }
    }
    if (window.katex) {
      for (const block of document.querySelectorAll(".block")) {
        if (block.classList.contains("is-editing")) continue;
        this.renderMathIn(block);
      }
    }
  },

  renderMathIn(root) {
    const RE = /(\$\$[^$]+\$\$|\$[^$\n]+\$)/;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (n.parentElement.closest("code, pre, .mermaid")) return NodeFilter.FILTER_REJECT;
        return RE.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const targets = [];
    while (walker.nextNode()) targets.push(walker.currentNode);
    for (const node of targets) {
      const parts = node.nodeValue.split(RE);
      const frag = document.createDocumentFragment();
      for (const part of parts) {
        const dm = /^\$\$([^$]+)\$\$$/.exec(part);
        const inline = /^\$([^$\n]+)\$$/.exec(part);
        if (dm || inline) {
          const span = document.createElement("span");
          try {
            span.innerHTML = katex.renderToString(dm ? dm[1] : inline[1], {
              displayMode: !!dm,
              throwOnError: false,
            });
          } catch (e) {
            span.textContent = part;
          }
          frag.appendChild(span);
        } else {
          frag.appendChild(document.createTextNode(part));
        }
      }
      node.replaceWith(frag);
    }
  },

  // ---------------- 鼠标 ----------------

  onMouseDown(e) {
    if (e.button !== undefined && e.button !== 0) return;
    const target = e.target;
    const clickedBlock = target.closest(".block");
    if (this.pendingTransform) {
      e.preventDefault();
      const index = clickedBlock ? Number(clickedBlock.dataset.index) : null;
      const x = e.clientX, y = e.clientY;
      this.pendingInput.push(() => this.switchTo(index === null ? this.blocks.length - 1 :
        Math.min(index, this.blocks.length - 1), {point:{x,y}}));
      return;
    }
    // A single click in document padding continues writing at the end.
    if (!clickedBlock) {
      if (!target.closest("#doc") && target !== document.body && target !== document.documentElement) return;
      e.preventDefault();
      this.switchTo(this.blocks.length - 1, {caret:0});
      return;
    }
    const idx = Number(clickedBlock.dataset.index);
    if (this.editingIndex === idx) return; // 已在编辑：原生定位
    e.preventDefault();
    const cell = target.closest("th,td");
    this.switchTo(idx, {point:{x:e.clientX,y:e.clientY},
      cell:cell ? [...clickedBlock.querySelectorAll("th,td")].indexOf(cell) : 0,
      task:target.matches("input.task-checkbox")});
  },

  // Every transition shares one queue: navigation never races a commit/transform.
  runBridge(method, args, apply) {
    const epoch = this.epoch;
    const serial = ++this.requestSerial;
    this.pendingTransform = true;
    this.bridge[method](...args, (s) => {
      if (epoch !== this.epoch) return;
      try { apply(JSON.parse(s)); }
      finally {
        if (serial === this.requestSerial) {
          this.pendingTransform = false;
          while (!this.pendingTransform && this.pendingInput.length) this.pendingInput.shift()();
        }
      }
    });
  },

  loadDocument(focus = false) {
    this.epoch++;
    this.pendingTransform = true;
    this.pendingInput = [];
    const epoch = this.epoch;
    this.bridge.loadBlocks((s) => {
      if (epoch !== this.epoch) return;
      this.renderAll(JSON.parse(s));
      this.pendingTransform = false;
      if (focus) this.focusEditor();
      while (!this.pendingTransform && this.pendingInput.length) this.pendingInput.shift()();
    });
  },

  switchTo(index, options = {}) {
    if (this.pendingTransform) { this.pendingInput.push(() => this.switchTo(index, options)); return; }
    if (index < 0 || index >= this.blocks.length) return;
    const enter = (idx) => {
      const block = document.querySelector(`.block[data-index="${idx}"]`);
      if (!block) return;
      if (options.task) {
        this.runBridge("toggleTask", [idx], (blocks) => {
          this.renderAll(blocks); this.focusBlock(idx);
        });
      } else if (this.blocks[idx].type === "table" && !options.raw) {
        const cells = [...block.querySelectorAll("th,td")];
        const cell = cells[options.cell === -1 ? cells.length - 1 : (options.cell || 0)];
        if (cell) this.attachTableEditor(block, idx, cell);
        else this.startEdit(idx, options.point, options.caret ?? null);
      } else {
        this.startEdit(idx, options.point, options.caret === "end" ? this.blocks[idx].raw.length : (options.caret ?? null));
        if (options.edge) this.placeOnEdge(block, options.edge, options.x);
      }
    };
    if (index === this.editingIndex) {
      const el = document.querySelector(".is-editing");
      el.focus({preventScroll:true});
      if (options.caret !== undefined) this.setCaret(el, options.caret === "end" ? el.textContent.length : options.caret);
      return;
    }
    const editingCell = document.querySelector("td[contenteditable=true],th[contenteditable=true]");
    if (editingCell) editingCell.blur();
    if (this.pendingTransform) { this.pendingInput.push(() => this.switchTo(index, options)); return; }
    if (this.editingIndex >= 0) {
      const raw = this.editingRaw();
      if (raw === this.blocks[this.editingIndex].raw) {
        this.renderAll(this.blocks);
        enter(index);
        return;
      }
      this.runBridge("commitAndLocate", [this.editingIndex, raw, index], (result) => {
        this.renderAll(result.blocks); enter(result.index);
      });
    } else enter(index);
  },

  focusBlock(index) {
    this.activeIndex = Math.max(0, Math.min(index, this.blocks.length - 1));
    const el = document.querySelector(`.block[data-index="${this.activeIndex}"]`);
    if (el) { el.focus({preventScroll:true}); this.markActive(this.activeIndex); }
  },

  focusEditor() {
    if (!this.blocks.length) return;
    if (this.editingIndex >= 0) {
      document.querySelector(".is-editing").focus({preventScroll:true});
    } else this.switchTo(this.activeIndex, {caret:this.lastCaret});
  },

  withEditor(action) {
    if (this.pendingTransform) { this.pendingInput.push(() => this.withEditor(action)); return; }
    if (this.editingIndex < 0) this.switchTo(this.activeIndex, {raw:true, caret:this.lastCaret});
    if (this.pendingTransform) this.pendingInput.push(() => this.withEditor(action));
    else {
      const el = document.querySelector(".is-editing");
      if (el) { el.focus({preventScroll:true}); action(el); }
    }
  },

  insertMarkdown(text) {
    this.withEditor(() => this.replaceSelection(text));
  },

  wrapSelection(before, after) {
    this.withEditor((el) => {
      const selection = this.selectionOffsets(el) || [el.textContent.length, el.textContent.length];
      const [start, end] = selection;
      const selected = el.textContent.slice(start, end);
      el.textContent = el.textContent.slice(0, start) + before + selected + after + el.textContent.slice(end);
      const range = this.caretRange(el, start + before.length);
      const finish = this.caretRange(el, start + before.length + selected.length);
      range.setEnd(finish.startContainer, finish.startOffset);
      getSelection().removeAllRanges(); getSelection().addRange(range);
      this.syncDraft();
    });
  },

  toggleCurrentTask() {
    this.withEditor((el) => {
      const offset = (this.selectionOffsets(el) || [0])[0];
      const start = el.textContent.lastIndexOf("\n", offset - 1) + 1;
      const end = el.textContent.indexOf("\n", offset);
      const line = el.textContent.slice(start, end < 0 ? undefined : end);
      const match = /^(\s*[-+*]\s+)\[([ xX])\]/.exec(line);
      const replaced = match ? line.replace(/\[([ xX])\]/, match[2] === " " ? "[x]" : "[ ]") : "- [ ] " + line;
      el.textContent = el.textContent.slice(0, start) + replaced + (end < 0 ? "" : el.textContent.slice(end));
      this.setCaret(el, offset + (match ? 0 : 6));
      this.syncDraft();
    });
  },

  jumpTo(index) {
    if (this.pendingTransform) { this.pendingInput.push(() => this.jumpTo(index)); return; }
    if (this.editingIndex >= 0) {
      this.runBridge("commit", [this.editingIndex, this.editingRaw()], (blocks) => {
        this.renderAll(blocks); this.switchTo(Math.min(index, blocks.length - 1), {caret:0});
      });
    } else this.switchTo(index, {caret:0});
  },

  jumpToLine(index, inBlockOffset) {
    if (this.pendingTransform) {
      this.pendingInput.push(() => this.jumpToLine(index, inBlockOffset));
      return;
    }
    const block = document.querySelector(`.block[data-index="${index}"]`);
    if (block) block.scrollIntoView({ block: "center" });
    // 进入该块并把光标放到块内偏移
    this.switchTo(index, { caret: Math.max(0, inBlockOffset) });
  },

  startEdit(index, point, fixedCaret = null) {
    if (!this.blocks[index]) return;
    const raw = this.blocks[index].raw;
    const el = document.querySelector(`.block[data-index="${index}"]`);
    if (!el) return;
    el.classList.add("is-editing");
    el.textContent = raw;
    el.contentEditable = "true";
    el.setAttribute("role", "textbox");
    el.setAttribute("aria-multiline", "true");
    el.focus({ preventScroll: true });
    this.editingIndex = index;
    this.activeIndex = index;
    this.markActive(index);
    let local = raw.length;
    if (fixedCaret !== null) {
      local = fixedCaret;
    } else if (point) {
      const range = document.caretRangeFromPoint(point.x, point.y);
      if (range && el.contains(range.startContainer)) {
        local = this.textOffset(el, range.startContainer, range.startOffset);
      }
    }
    this.setCaret(el, local);
  },

  commitEdit() {
    if (this.pendingTransform) { this.pendingInput.push(() => this.commitEdit()); return; }
    if (this.editingIndex < 0) return;
    const raw = this.editingRaw();
    const idx = this.editingIndex;
    this.runBridge("commit", [idx, raw], (blocks) => {
      this.renderAll(blocks); this.focusBlock(Math.min(idx, blocks.length - 1));
    });
  },

  editingRaw() {
    const el = document.querySelector(`.block[data-index="${this.editingIndex}"]`);
    return el ? el.textContent : "";
  },

  syncDraft() {
    if (this.editingIndex >= 0) {
      this.bridge.updateDraft(this.editingIndex, this.editingRaw());
    }
  },

  // ---------------- 按键 ----------------

  onKeyDown(e) {
    if (e.defaultPrevented) return;
    if (e.isComposing || e.keyCode === 229) return; // IME 组字保护
    if (this.pendingTransform && (["Enter", "Tab", "Backspace", "Delete", "Escape", " ",
        "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown", "F2"].includes(e.key) ||
        (e.key === '"' && window.__smartQuotes))) {
      e.preventDefault();
      const options = {key:e.key, shiftKey:e.shiftKey, ctrlKey:e.ctrlKey, altKey:e.altKey, metaKey:e.metaKey,
        bubbles:true, cancelable:true};
      this.pendingInput.push(() => {
        const replay = new KeyboardEvent("keydown", options);
        document.activeElement.dispatchEvent(replay);
        if (!replay.defaultPrevented && ["Backspace", "Delete"].includes(options.key)) {
          document.execCommand(options.key === "Backspace" ? "delete" : "forwardDelete");
        }
      });
      return;
    }
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && !e.altKey) {
      const key = e.key.toLowerCase();
      const marker = !e.shiftKey && key === "b" ? "**" : !e.shiftKey && key === "i" ? "*" :
        e.shiftKey && key === "x" ? "~~" : e.shiftKey && key === "`" ? "`" : null;
      if (marker) { e.preventDefault(); this.wrapSelection(marker, marker); return; }
      if (key === "k" && !e.shiftKey) { e.preventDefault(); this.wrapSelection("[", "](https://)"); return; }
      if (key === "z" || key === "y") {
        e.preventDefault(); this.history(key === "y" || e.shiftKey ? "redo" : "undo"); return;
      }
    }
    if (ctrl && !e.shiftKey && ["Home", "End"].includes(e.key)) {
      e.preventDefault();
      this.switchTo(e.key === "Home" ? 0 : this.blocks.length - 1, {caret:0});
      return;
    }
    if ((ctrl && e.key === "Tab") || (ctrl && ["ArrowUp", "ArrowDown"].includes(e.key))) {
      e.preventDefault();
      const backwards = e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey);
      this.switchTo(this.activeIndex + (backwards ? -1 : 1), {caret:backwards ? "end" : 0, cell:backwards ? -1 : 0});
      return;
    }
    if (e.key === "F2") {
      e.preventDefault();
      this.switchTo(this.activeIndex, {raw:true, caret:0});
      return;
    }
    if (this.editingIndex < 0) {
      if (["Enter", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) {
        e.preventDefault();
        const delta = ["ArrowUp", "ArrowLeft"].includes(e.key) ? -1 : e.key === "Enter" ? 0 : 1;
        this.switchTo(Math.max(0, Math.min(this.blocks.length - 1, this.activeIndex + delta)), {caret:0});
      } else if (!ctrl && !e.altKey && e.key.length === 1 && !e.target.closest("th,td")) {
        e.preventDefault();
        this.switchTo(this.activeIndex, {caret:this.lastCaret});
        this.replaceSelection(e.key);
      }
      return;
    }
    const el = document.querySelector(".block.is-editing");
    if (!el) return;
    const selection = this.selectionOffsets(el);
    if (!selection) return;
    const [off, end] = selection;
    const raw = el.textContent.slice(0, off) + el.textContent.slice(end);
    const key = e.key;

    if (!key.startsWith("Arrow")) this.verticalX = null;
    if (!e.shiftKey && off === end) {
      if ((key === "ArrowLeft" && off === 0) || (key === "ArrowRight" && end === el.textContent.length)) {
        e.preventDefault();
        this.switchTo(this.editingIndex + (key === "ArrowLeft" ? -1 : 1), {caret:key === "ArrowLeft" ? "end" : 0});
        return;
      }
      if (["ArrowUp", "ArrowDown"].includes(key)) {
        const rect = this.caretRect(el, off);
        const edge = this.caretRect(el, key === "ArrowUp" ? 0 : el.textContent.length);
        if (Math.abs(rect.top - edge.top) < Math.max(2, rect.height / 2)) {
          e.preventDefault();
          this.verticalX ??= rect.left;
          this.switchTo(this.editingIndex + (key === "ArrowUp" ? -1 : 1),
            {edge:key === "ArrowUp" ? "end" : "start", x:this.verticalX, cell:key === "ArrowUp" ? -1 : 0});
          return;
        }
      }
      if (["PageUp", "PageDown"].includes(key)) {
        e.preventDefault();
        const direction = key === "PageUp" ? -1 : 1;
        const rect = this.caretRect(el, off);
        const y = rect.top + direction * window.innerHeight * .8;
        let index = this.editingIndex;
        for (let i = index + direction; i >= 0 && i < this.blocks.length; i += direction) {
          index = i;
          const b = document.querySelector(`.block[data-index="${i}"]`).getBoundingClientRect();
          if (direction > 0 ? b.bottom >= y : b.top <= y) break;
        }
        this.switchTo(index, {caret:direction > 0 ? 0 : "end"});
        return;
      }
    }

    if (key === "Enter") {
      e.preventDefault();
      this.requestTransform(el, "enter", off, raw);
    } else if (key === "Backspace" && off === 0 && off === end) {
      e.preventDefault();
      this.requestTransform(el, "backspace", off, el.textContent);
    } else if (key === "Tab") {
      e.preventDefault();
      this.requestTransform(el, e.shiftKey ? "shiftTab" : "tab", off, el.textContent);
    } else if (key === " ") {
      e.preventDefault();
      const spaced = raw.slice(0, off) + " " + raw.slice(off);
      el.textContent = spaced;
      this.setCaret(el, off + 1);
      this.syncDraft();
      this.requestTransform(el, "spaceProbe", off + 1, spaced);
    } else if (key === '"' && window.__smartQuotes) {
      e.preventDefault();
      this.insertPaired("“", "”");
    } else if (key === "Escape") {
      e.preventDefault();
      this.commitEdit();
    }
  },

  requestTransform(el, command, offset, raw) {
    this.runBridge("transform", [this.editingIndex, command, offset, raw], (st) => {
        if (st && st.enter) {
          this.renderAll(st.blocks);
          this.startEdit(st.enter.index, null, st.enter.caret);
        } else if (st) {
          this.applyInline(el, st);
        }
    });
  },

  history(command) {
    if (this.pendingTransform) { this.pendingInput.push(() => this.history(command)); return; }
    const index = this.activeIndex;
    this.runBridge(command, [], (blocks) => {
      this.renderAll(blocks);
      this.switchTo(Math.min(index, blocks.length - 1), {caret:"end"});
    });
  },

  /** 在光标处插入一对符号，光标置于两者之间 */
  insertPaired(open, close) {
    const el = document.querySelector(".block.is-editing");
    const sel = getSelection();
    const off = this.textOffset(el, sel.anchorNode, sel.anchorOffset);
    const text = el.textContent;
    el.textContent = text.slice(0, off) + open + close + text.slice(off);
    this.setCaret(el, off + 1);
    this.syncDraft();
  },

  /** 应用同块变换；若块索引变化则整体重渲染后进入目标块。 */
  applyInline(el, st) {
    if (st.blocks) {
      this.renderAll(st.blocks);
      this.startEdit(st.index, null, st.caret);
    } else {
      el.textContent = st.text;
      this.setCaret(el, st.caret);
    }
  },

  // ---------------- 活动块 / 打字机 ----------------

  markActive(idx) {
    document.querySelectorAll(".block.block-active").forEach((b) =>
      b.classList.remove("block-active")
    );
    if (idx !== null && idx !== undefined) {
      const el = document.querySelector(`.block[data-index="${idx}"]`);
      if (el) el.classList.add("block-active");
    }
  },

  scrollTypewriter() {
    if (!window.__typewriter) return;
    const sel = getSelection();
    if (!sel.rangeCount) return;
    const rect = sel.getRangeAt(0).cloneRange().getBoundingClientRect();
    if (!rect.height && !rect.top) return;
    const target = rect.top + rect.height / 2 - window.innerHeight / 2;
    if (Math.abs(target) > 4) window.scrollBy(0, target);
  },

  // ---------------- 选区工具 ----------------

  caretRange(root, offset) {
    if (!root.firstChild) root.appendChild(document.createTextNode(""));
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode(), remaining = Math.max(0, offset), last = node;
    while (node) {
      last = node;
      if (remaining <= node.textContent.length) break;
      remaining -= node.textContent.length;
      node = walker.nextNode();
    }
    const range = document.createRange();
    range.setStart(node || last, node ? remaining : last.textContent.length);
    range.collapse(true);
    return range;
  },

  caretRect(root, offset) {
    const rect = this.caretRange(root, offset).getBoundingClientRect();
    return rect.height ? rect : root.getBoundingClientRect();
  },

  placeOnEdge(root, edge, x) {
    const fallback = edge === "end" ? root.textContent.length : 0;
    const rect = this.caretRect(root, fallback);
    const bounds = root.getBoundingClientRect();
    // Scroll the target line into view before using viewport hit testing.
    if (rect.top < 0 || rect.bottom > window.innerHeight) {
      window.scrollBy(0, rect.top - window.innerHeight / 2);
    }
    const line = this.caretRect(root, fallback);
    const range = document.caretRangeFromPoint(Math.max(bounds.left + 13, Math.min(x, bounds.right - 13)), line.top + line.height / 2);
    const offset = range && root.contains(range.startContainer) ?
      this.textOffset(root, range.startContainer, range.startOffset) : fallback;
    this.setCaret(root, offset);
  },

  selectionOffsets(root) {
    const sel = getSelection();
    if (!sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
    return [this.textOffset(root, range.startContainer, range.startOffset),
      this.textOffset(root, range.endContainer, range.endOffset)];
  },

  replaceSelection(text) {
    const el = document.querySelector(".block.is-editing");
    if (!el) return;
    const selection = this.selectionOffsets(el);
    if (!selection) return;
    const [start, end] = selection;
    el.textContent = el.textContent.slice(0, start) + text + el.textContent.slice(end);
    this.setCaret(el, start + text.length);
    this.syncDraft();
  },

  textOffset(root, container, offset) {
    const r = document.createRange();
    r.selectNodeContents(root);
    r.setEnd(container, offset);
    return r.toString().length;
  },

  setCaret(root, offset) {
    const range = this.caretRange(root, offset);
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    this.lastCaret = Math.min(offset, root.textContent.length);
    const rect = range.getBoundingClientRect();
    if (rect.height && (rect.top < 12 || rect.bottom > window.innerHeight - 12)) {
      window.scrollBy(0, rect.top < 12 ? rect.top - 12 : rect.bottom - window.innerHeight + 12);
    }
    this.scrollTypewriter();
  },
};

// QWebChannel 就绪后启动
window.addEventListener("DOMContentLoaded", () => {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    App.init(channel.objects.bridge);
  });
});
