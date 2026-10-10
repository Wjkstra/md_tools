// Continuous (Typora-style) live editor.
//
// The whole document lives in one contenteditable surface (#doc), so the native
// caret/selection can cross headings/paragraphs/lists/quotes/tables: blank lines,
// Ctrl+A and multi-paragraph selection just work. Complex blocks (code, Mermaid,
// block math, front matter) are non-editable "atoms"; clicking one opens an
// inline plaintext source editor. After any edit the surface DOM is converted
// back to Markdown via HtmlToMd and pushed to Python.
"use strict";

const App = {
  bridge: null,
  surfaceReady: false,
  activeAtom: null,    // atom element currently in source-edit mode
  syncTimer: null,

  // ------------------------------------------------ init -------------------

  init(bridge) {
    this.bridge = bridge;
    document.addEventListener("click", (e) => this.onClick(e));
    document.addEventListener("keydown", (e) => this.onKeyDown(e));
    document.addEventListener("beforeinput", (e) => this.onBeforeInput(e));
    document.addEventListener("input", (e) => this.onInput(e));
    this.loadSurface();
  },

  // Auto-pair opening marks: typing one around a selection wraps it, otherwise
  // inserts the pair; typing a closing mark skips an existing one.
  PAIRS: { "[": "]", "(": ")", "{": "}", "`": "`", '"': '"' },

  onBeforeInput(event) {
    if (this.activeAtom || !window.__autoBracket ||
        event.inputType !== "insertText" || !event.data) {
      return;
    }
    const char = event.data;
    if (!(char in this.PAIRS)) {
      // Closing mark right before an identical existing one: skip it.
      const close = Object.values(this.PAIRS).includes(char);
      if (close) {
        const selection = getSelection();
        if (selection.rangeCount && selection.isCollapsed) {
          const node = selection.anchorNode;
          if (node.nodeType === 3 && node.data[selection.anchorOffset] === char) {
            event.preventDefault();
            const range = document.createRange();
            range.setStart(node, selection.anchorOffset + 1);
            range.collapse(true);
            selection.removeAllRanges(); selection.addRange(range);
          }
        }
      }
      return;
    }
    const selection = getSelection();
    if (!selection.rangeCount) return;
    if (!selection.isCollapsed) {
      event.preventDefault();
      this.wrapSelection(char, this.PAIRS[char]);
    } else {
      event.preventDefault();
      this.insertPair(char, this.PAIRS[char]);
    }
  },

  insertPair(open, close) {
    const selection = getSelection();
    const range = selection.getRangeAt(0);
    range.insertNode(document.createTextNode(open + close));
    const node = range.startContainer;
    const offset = range.startOffset - 1 + open.length;
    const caret = this.caretRange(node, offset);
    selection.removeAllRanges(); selection.addRange(caret);
  },

  loadSurface() {
    this.surfaceReady = false;
    Promise.resolve(this.bridge.loadSurfaceHtml())
      .then((raw) => {
        const html = JSON.parse(raw);
        const doc = document.getElementById("doc");
        doc.contentEditable = "true";
        doc.innerHTML = html;
        this.postProcess(doc);
        this.surfaceReady = true;
      })
      .catch((error) => {
        window.__loadErr = String(error && error.message || error);
      });
  },

  // Render Mermaid atoms (code atom stays plain, math atom shows source).
  postProcess(doc) {
    doc.querySelectorAll(".atom-diagram").forEach((atom) => {
      if (window.mermaid && !atom.dataset.rendered) {
        atom.dataset.rendered = "1";
        try {
          window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict",
            theme: "neutral" });
          const result = window.mermaid.run({ nodes: [atom.querySelector(".mermaid")] });
          if (result && result.catch) result.catch(() => {});
        } catch (e) { /* keep source visible */ }
      }
    });
  },

  // ------------------------------------------------ sync -------------------

  scheduleSync() {
    if (this.syncTimer) clearTimeout(this.syncTimer);
    this.syncTimer = setTimeout(() => this.pushSurface(), 120);
  },

  pushSurface() {
    const md = HtmlToMd.serialize(document.getElementById("doc"));
    this.bridge.updateSurfaceText(md);
  },

  onInput() {
    if (this.activeAtom) return; // atom edits sync on commit
    this.scheduleSync();
  },

  // Wrap the current selection in inline marks; with no selection insert a pair.
  wrapSelection(before, after) {
    const selection = getSelection();
    if (!selection.rangeCount) return;
    const text = selection.toString();
    const range = selection.getRangeAt(0);
    range.deleteContents();
    range.insertNode(document.createTextNode(before + text + after));
    // Select the inserted text (between the marks) for continued typing.
    const node = range.startContainer;
    const start = (range.startOffset - text.length) + before.length;
    const caret = this.caretRange(node, start);
    const endRange = this.caretRange(node, start + text.length);
    caret.setEnd(endRange.startContainer, endRange.startOffset);
    selection.removeAllRanges(); selection.addRange(caret);
    this.scheduleSync();
  },

  caretRange(root, offset) {
    const range = document.createRange();
    if (root.nodeType === 3) {
      range.setStart(root, Math.min(offset, root.length));
    } else {
      range.setStart(root, offset);
    }
    range.collapse(true);
    return range;
  },

  insertLink() {
    const text = getSelection().toString() || "链接文字";
    this.wrapSelection("[", "](https://)");
  },

  // Scroll the block at the given model block index into view (surface children
  // follow the block order, including the trailing end block).
  jumpToBlock(index) {
    const child = document.getElementById("doc").children[Math.max(0, index)];
    if (child) {
      child.scrollIntoView({ block: "start" });
      const range = document.createRange();
      range.selectNodeContents(child); range.collapse(true);
      const selection = getSelection();
      selection.removeAllRanges(); selection.addRange(range);
    }
  },

  // Native in-page find over the rendered surface. Returns match info.
  findText(text, forward = true) {
    if (!text) return JSON.stringify({ found: false, total: 0 });
    const total = this.countMatches(text);
    const found = window.find(text, false, !forward, true, false, true, false);
    return JSON.stringify({ found: found, total: total });
  },

  countMatches(text) {
    // window.find advances the caret; count over the body text cheaply by a
    // case-insensitive split on the literal text.
    const body = document.getElementById("doc").textContent;
    if (!text) return 0;
    const lower = body.toLowerCase(), q = text.toLowerCase();
    let count = 0, at = 0;
    while ((at = lower.indexOf(q, at)) >= 0) { count += 1; at += q.length; }
    return count;
  },

  // ------------------------------------------------ atoms ------------------

  onClick(event) {
    const atom = event.target.closest && event.target.closest(".md-atom");
    if (atom && !this.activeAtom) {
      event.preventDefault();
      this.editAtom(atom);
    }
  },

  editAtom(atom) {
    this.activeAtom = atom;
    atom.dataset.mdBefore = atom.getAttribute("data-md");
    // One plaintext-only editor carrying the verbatim original Markdown.
    atom.setAttribute("contenteditable", "plaintext-only");
    atom.textContent = atom.dataset.mdBefore;
    atom.classList.add("atom-editing");
    atom.focus();
  },

  commitAtom(apply) {
    const atom = this.activeAtom;
    if (!atom) return;
    const md = atom.textContent;
    if (apply && md !== atom.dataset.mdBefore) {
      atom.setAttribute("data-md", md);
      this.bridge.updateSurfaceText(
        HtmlToMd.serialize(document.getElementById("doc")));
    }
    this.activeAtom = null;
    this.loadSurface(); // re-render; keeps the model and surface consistent
  },

  // Character offset of the caret inside an editable element.
  textOffset(root) {
    const selection = getSelection();
    if (!selection.rangeCount) return 0;
    const range = document.createRange();
    range.selectNodeContents(root);
    try { range.setEnd(selection.anchorNode, selection.anchorOffset); }
    catch (error) { return 0; }
    return range.toString().length;
  },

  // Insert text at the caret (works after preventDefault).
  insertAtCaret(text) {
    document.execCommand("insertText", false, text);
  },

  // ---------------- code editing ----------------

  onCodeKeyDown(event, area) {
    const tabSize = window.__tabSize || 2;
    if (event.key === "Enter") {
      event.preventDefault();
      const text = area.textContent;
      const offset = this.textOffset(area);
      const before = text.slice(0, offset);
      const lineStart = before.lastIndexOf("\n") + 1;
      const currentLine = before.slice(lineStart);
      const indent = (currentLine.match(/^[ \t]*/) || [""])[0];
      // Unclosed block (more { than } so far): indent one more level.
      const opens = (before.match(/{/g) || []).length;
      const closes = (before.match(/}/g) || []).length;
      const extra = opens > closes ? " ".repeat(tabSize) : "";
      this.insertAtCaret("\n" + indent + extra);
      this.scheduleSync();
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      if (event.shiftKey) {
        const text = area.textContent;
        const offset = this.textOffset(area);
        const lineStart = text.lastIndexOf("\n", offset - 1) + 1;
        const leading = (text.slice(lineStart).match(/^ +/) || [""])[0].length;
        const removed = Math.min(tabSize, leading);
        if (removed > 0) {
          const selection = getSelection();
          const node = selection.anchorNode;
          const at = selection.anchorOffset;
          const range = document.createRange();
          range.setStart(node, Math.max(0, at - removed));
          range.setEnd(node, at);
          range.deleteContents();
        }
      } else {
        this.insertAtCaret(" ".repeat(tabSize));
      }
      this.scheduleSync();
    }
  },

  // ---------------- table editing ----------------

  onTableKeyDown(event, cell) {
    if (event.ctrlKey && event.key === "Enter") {
      event.preventDefault();
      this.insertTableRow(cell);
      this.scheduleSync();
    } else if (event.altKey && event.key === "Enter") {
      event.preventDefault();
      this.insertTableColumn(cell);
      this.scheduleSync();
    }
  },

  insertTableRow(cell) {
    const row = cell.closest("tr");
    const isHead = !!row.closest("thead");
    if (isHead) {
      // From the header, add a row at the top of the body.
      const tbody = row.closest("table").querySelector("tbody")
        || row.closest("table").appendChild(document.createElement("tbody"));
      const count = row.children.length;
      const tr = document.createElement("tr");
      for (let i = 0; i < count; i++) {
        tr.appendChild(document.createElement("td")).appendChild(document.createElement("br"));
      }
      tbody.prepend(tr);
      return;
    }
    const copy = row.cloneNode(true);
    Array.from(copy.children).forEach((td) => { td.textContent = ""; td.appendChild(document.createElement("br")); });
    row.after(copy);
  },

  insertTableColumn(cell) {
    const table = cell.closest("table");
    const cellIndex = Array.from(cell.parentElement.children).indexOf(cell);
    table.querySelectorAll("tr").forEach((tr) => {
      const isHeadRow = !!tr.closest("thead");
      const fresh = document.createElement(isHeadRow ? "th" : "td");
      fresh.appendChild(document.createElement("br"));
      const reference = tr.children[cellIndex + 1] || null;
      tr.insertBefore(fresh, reference);
    });
  },

  onKeyDown(event) {
    // Keystrokes inside an atom that is in source-edit mode.
    if (this.activeAtom) {
      const ctrl = event.ctrlKey || event.metaKey;
      if (event.key === "Escape") {
        event.preventDefault(); this.commitAtom(false);
      } else if (ctrl && event.key === "Enter") {
        event.preventDefault(); this.commitAtom(true);
      }
      return;
    }
    // Context: code area or table cell.
    const codeArea = event.target.closest && event.target.closest(".md-code-area");
    if (codeArea) { this.onCodeKeyDown(event, codeArea); return; }
    const tableCell = event.target.closest && event.target.closest("th,td");
    if (tableCell && (event.ctrlKey || event.altKey) && event.key === "Enter") {
      this.onTableKeyDown(event, tableCell); return;
    }
    // Inline format shortcuts in the continuous surface.
    const ctrl = event.ctrlKey || event.metaKey;
    if (ctrl && !event.shiftKey) {
      const key = event.key.toLowerCase();
      if (key === "b") { event.preventDefault(); this.wrapSelection("**", "**"); return; }
      if (key === "i") { event.preventDefault(); this.wrapSelection("*", "*"); return; }
      if (key === "k") { event.preventDefault(); this.insertLink(); return; }
    }
  },
};

// QWebChannel ready -> start.
window.addEventListener("DOMContentLoaded", () => {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    App.init(channel.objects.bridge);
  });
});
