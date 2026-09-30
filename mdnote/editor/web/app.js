// 实时模式前端控制器：块渲染 / 点击编辑 / 按键经 QWebChannel 交给 Python 计算。
"use strict";

const App = {
  blocks: [],
  editingIndex: -1,
  bridge: null,
  pendingTransform: false,
  pendingInput: [],

  init(bridge) {
    this.bridge = bridge;
    document.addEventListener("mousedown", (e) => this.onMouseDown(e), true);
    document.addEventListener("keydown", (e) => this.onKeyDown(e));
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
    bridge.loadBlocks((s) => this.renderAll(JSON.parse(s)));
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
    if (!table.dataset.bound) {
      table.dataset.bound = "1";
      for (const cell of table.querySelectorAll("th,td")) {
        cell.setAttribute("tabindex", "-1");
        cell.addEventListener("click", () => this.editCell(cell, table, index));
        cell.addEventListener("input", () => this.submitTable(table, index));
        cell.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            cell.blur();
          } else if (e.key === "Tab") {
            e.preventDefault();
            const cells = [...table.querySelectorAll("th,td")];
            const i = cells.indexOf(cell);
            const next = cells[i + (e.shiftKey ? -1 : 1)];
            if (next) {
              cell.blur();
              this.editCell(next, table, index);
            }
          }
        });
        cell.addEventListener("blur", () => {
          if (cell.isContentEditable) {
            cell.contentEditable = "false";
            this.submitTable(table, index); // 静默回写，不打断连续编辑
          }
        });
      }
    }
    const cell = target.closest("th,td");
    if (cell) this.editCell(cell, table, index);
  },

  editCell(cell, table, index) {
    cell.contentEditable = "true";
    cell.focus();
  },

  submitTable(table, index) {
    const md = this.tableToMarkdown(table);
    this.bridge.updateTable(index, md, (s) => { this.blocks = JSON.parse(s); });
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

  renderAll(blocks) {
    this.blocks = blocks;
    this.editingIndex = -1;
    const doc = document.getElementById("doc");
    doc.replaceChildren();
    for (const b of blocks) {
      const el = document.createElement("div");
      el.className = `block block-${b.type}`;
      el.dataset.index = String(b.index);
      if (b.trailing) el.classList.add("block-trailing");
      el.innerHTML = b.html;
      doc.appendChild(el);
    }
    this.postProcess();
  },

  postProcess() {
    // TOC 链接：滚动到对应标题
    for (const link of document.querySelectorAll(".toc-link")) {
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
    const target = e.target;
    const clickedBlock = target.closest(".block");
    const clickedIndex = clickedBlock ? Number(clickedBlock.dataset.index) : -1;
    if (this.editingIndex >= 0 && clickedIndex >= 0 && clickedIndex !== this.editingIndex) {
      e.preventDefault();
      const cell = target.closest("th,td");
      const cellIndex = cell ? [...clickedBlock.querySelectorAll("th,td")].indexOf(cell) : -1;
      const checkboxIndex = [...clickedBlock.querySelectorAll("input.task-checkbox")].indexOf(target);
      this.bridge.commitAndLocate(this.editingIndex, this.editingRaw(), clickedIndex, (s) => {
        const result = JSON.parse(s);
        this.renderAll(result.blocks);
        const block = document.querySelector(`.block[data-index="${result.index}"]`);
        const next = cellIndex >= 0 ? block.querySelectorAll("th,td")[cellIndex] :
          checkboxIndex >= 0 ? block.querySelectorAll("input.task-checkbox")[checkboxIndex] : block;
        if (next) this.onMouseDown({target:next, clientX:e.clientX, clientY:e.clientY, preventDefault() {}});
      });
      return;
    }
    if (target.matches("input.task-checkbox")) {
      e.preventDefault();
      const idx = Number(target.closest(".block").dataset.index);
      this.bridge.toggleTask(idx, (s) => this.renderAll(JSON.parse(s)));
      return;
    }
    const blockEl = target.closest(".block");
    if (!blockEl) {
      this.markActive(null);
      if (this.editingIndex >= 0) this.commitEdit();
      return;
    }
    const idx = Number(blockEl.dataset.index);
    this.markActive(idx);

    // 表格块：走单元格可视化编辑，而不是整块 raw 源码
    if (this.blocks[idx] && this.blocks[idx].type === "table") {
      e.preventDefault();
      this.attachTableEditor(blockEl, idx, target);
      return;
    }

    if (this.editingIndex === idx) return; // 已在编辑：原生定位

    e.preventDefault();
    const point = { x: e.clientX, y: e.clientY };
    this.startEdit(idx, point);
  },

  startEdit(index, point, fixedCaret = null) {
    if (!this.blocks[index]) return;
    const raw = this.blocks[index].raw;
    const el = document.querySelector(`.block[data-index="${index}"]`);
    if (!el) return;
    el.classList.add("is-editing");
    el.textContent = raw;
    el.contentEditable = "true";
    el.focus({ preventScroll: true });
    this.editingIndex = index;
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
    const raw = this.editingRaw();
    const idx = this.editingIndex;
    this.bridge.commit(idx, raw, (s) => this.renderAll(JSON.parse(s)));
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
    if (this.editingIndex < 0) return;
    if (e.isComposing || e.keyCode === 229) return; // IME 组字保护
    if (this.pendingTransform && (["Enter", "Tab", "Backspace", "Delete", "Escape", " "].includes(e.key) ||
        (e.key === '"' && window.__smartQuotes))) {
      e.preventDefault();
      const options = {key:e.key, shiftKey:e.shiftKey, bubbles:true, cancelable:true};
      this.pendingInput.push(() => {
        const replay = new KeyboardEvent("keydown", options);
        document.activeElement.dispatchEvent(replay);
        if (!replay.defaultPrevented && ["Backspace", "Delete"].includes(options.key)) {
          document.execCommand(options.key === "Backspace" ? "delete" : "forwardDelete");
        }
      });
      return;
    }
    const el = document.querySelector(".block.is-editing");
    if (!el) return;
    const selection = this.selectionOffsets(el);
    if (!selection) return;
    const [off, end] = selection;
    const raw = el.textContent.slice(0, off) + el.textContent.slice(end);
    const key = e.key;

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
    this.pendingTransform = true;
    this.bridge.transform(this.editingIndex, command, offset, raw, (s) => {
      try {
        const st = JSON.parse(s);
        if (st && st.enter) {
          this.renderAll(st.blocks);
          this.startEdit(st.enter.index, null, st.enter.caret);
        } else if (st) {
          this.applyInline(el, st);
        }
      } finally {
        this.pendingTransform = false;
        while (!this.pendingTransform && this.pendingInput.length) this.pendingInput.shift()();
      }
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
    if (!root.firstChild) root.appendChild(document.createTextNode(""));
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let remaining = offset;
    let node = walker.nextNode();
    while (node) {
      const len = node.textContent.length;
      if (remaining <= len) {
        const range = document.createRange();
        range.setStart(node, remaining);
        range.collapse(true);
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        this.scrollTypewriter();
        return;
      }
      remaining -= len;
      node = walker.nextNode();
    }
  },
};

// QWebChannel 就绪后启动
window.addEventListener("DOMContentLoaded", () => {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    App.init(channel.objects.bridge);
  });
});
