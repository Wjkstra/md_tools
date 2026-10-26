// Continuous (Typora-style) live editor.
//
// The whole document lives in one contenteditable surface (#doc), so the native
// caret/selection can cross headings/paragraphs/lists/quotes/tables: blank lines,
// Ctrl+A and multi-paragraph selection just work. Code has a persistent editor
// with a separate highlight mirror and live Mermaid preview. Complex blocks (math, front matter)
// are atoms with an inline source editor. After any edit the surface is converted
// back to Markdown via HtmlToMd and pushed to Python.
"use strict";

const App = {
  // Number of code blocks highlighted eagerly after a render; the rest are
  // highlighted lazily as they approach the viewport (long-document perf).
  CODE_HIGHLIGHT_HEAD: 8,
  bridge: null,
  surfaceReady: false,
  activeAtom: null,    // atom element currently in source-edit mode
  syncTimer: null,

  // The atom only counts as active while it is still in the live DOM:
  // a surface rebuild (save/reload/mode switch) replaces its element, and a
  // stale detached reference would swallow every later keystroke.
  editingAtom() {
    if (this.activeAtom && !this.activeAtom.isConnected) {
      this.activeAtom = null;
    }
    return this.activeAtom;
  },

  // ------------------------------------------------ init -------------------

  init(bridge) {
    this.bridge = bridge;
    document.addEventListener("click", (e) => this.onClick(e));
    document.addEventListener("keydown", (e) => this.onKeyDown(e));
    document.addEventListener("keyup", () => this.updateHeadingHint());
    document.addEventListener("beforeinput", (e) => this.onBeforeInput(e));
    document.addEventListener("input", (e) => this.onInput(e));
    document.addEventListener("compositionend", (e) => this.onCompositionEnd(e));
    document.addEventListener("mousedown", (e) => this.onMouseDown(e), true);
    document.addEventListener("selectionchange", () => this.scheduleHint());
    document.addEventListener("paste",event=>{
      if(this.editingAtom()) return;
      const area=event.target.closest?.(".md-code-area");
      if(area){
        event.preventDefault();
        const text=(event.clipboardData?.getData("text/plain")||"").replace(/\r\n?/g,"\n");
        const {start,end}=this.offsets(area);
        this.applyCodeEdit(area,{start,end,text,caret:start+text.length});return;
      }
      const source=event.clipboardData?.getData("text/plain")||"";
      if(document.getElementById("doc").contains(event.target) &&
         /(^|\n)\s{0,3}(\x60{3,}|~{3,})/.test(source)){
        event.preventDefault();this.insertMarkdown(source);
      }
    });
    this.loadSurface();
  },

  // Capture-phase mousedown delegation: reliably flips task checkboxes even
  // though they live inside a contenteditable surface (where normal clicks
  // only place the caret and never toggle the input).
  onMouseDown(event) {
    if (this.languagePicker && !this.languagePicker.contains(event.target)) {
      this.languagePicker.close();
    }
    document.querySelectorAll(".atom-diagram.is-diagram-editing").forEach(block=>{
      if (!block.contains(event.target)) this.setDiagramEditing(block,false);
    });
    const cb = event.target.closest && event.target.closest("input.task-checkbox");
    if (cb && document.getElementById("doc").contains(cb)) {
      event.preventDefault();
      event.stopPropagation();
      const now = !cb.hasAttribute("checked");
      cb.toggleAttribute("checked", now);
      cb.checked = now;
      this.scheduleSync();
    }
  },

  // Floating H[x] hint shown to the left when the caret is at the start of a
  // heading line (Typora-style).
  hintTimer: null,
  hintEl: null,
  hintState: false,

  ensureHint() {
    if (this.hintEl) return this.hintEl;
    const el = document.createElement("div");
    el.id = "heading-hint";
    el.hidden = true;
    document.body.appendChild(el);
    this.hintEl = el;
    return el;
  },
  scheduleHint() {
    if (this.hintTimer) return;
    this.hintTimer = requestAnimationFrame(() => {
      this.hintTimer = null;
      this.updateHeadingHint();
    });
  },
  updateHeadingHint() {
    if(this.fenceCompletion && this.selectionElement()?.closest("p")!==this.fenceCompletion.paragraph)
      this.fenceCompletion.menu.close();
    const el = this.ensureHint();
    const selection = getSelection();
    if (!selection.rangeCount || this.editingAtom()) { el.hidden = true; return; }
    const node = selection.anchorNode;
    const host = node && (node.nodeType === 1 ? node : node.parentElement);
    const heading = host && host.closest ? host.closest("h1,h2,h3,h4,h5,h6") : null;
    const inCode = heading && heading.closest(".md-code, table, .md-atom");
    // Only at the very start of the heading (plain-text offset 0).
    const atStart = heading && this.caretOffsetIn(heading) === 0;
    if (!inCode && atStart) {
      const level = Number(heading.tagName[1]);
      el.textContent = "H" + level;
      const rect = heading.getBoundingClientRect();
      el.hidden = false;
      // Float just left of the heading (viewport coords; CSS position:fixed).
      el.style.top = (rect.top + rect.height / 2) + "px";
      el.style.left = Math.max(6, rect.left - el.offsetWidth - 14) + "px";
    } else {
      el.hidden = true;
    }
  },

  // Auto-pair opening marks: typing one around a selection wraps it, otherwise
  // inserts the pair; typing a closing mark skips an existing one.
  PAIRS: { "[": "]", "(": ")", "{": "}", "`": "`", '"': '"' },
  // Marks the editor may have inserted as an auto-paired closer.
  CLOSERS: ["]", ")", "}", "\x60", '"'],

  // Caret context for auto-pairing: the character right after the caret, and how
  // many copies of the typed character sit immediately before it.
  caretContext(char) {
    const selection = getSelection();
    if (!selection.rangeCount || !selection.isCollapsed) return null;
    const node = selection.anchorNode;
    if (!node || node.nodeType !== 3) return { node: null, at: 0, next: "", run: 0 };
    const at = selection.anchorOffset;
    let run = 0;
    while (at - run - 1 >= 0 && node.data[at - run - 1] === char) run += 1;
    return { node, at, next: node.data[at] || "", run };
  },

  onBeforeInput(event) {
    if (event.isComposing || !document.getElementById("doc").contains(event.target)) return;
    if(event.target.closest?.(".md-code-tools")) return;
    const codeArea=event.target.closest?.(".md-code-area")||this.selectionElement()?.closest(".md-code-area");
    if(codeArea) {
      if(window.__autoBracket && event.inputType==="insertText" && event.data) {
        const {start,end}=this.offsets(codeArea);
        const edit=CodeEditing.pair(HtmlToMd.codeText(codeArea),start,end,event.data,codeArea.closest(".md-code").dataset.lang);
        if(edit){event.preventDefault();this.applyCodeEdit(codeArea,edit);}
      }
      return;
    }
    if (this.editingAtom() || !window.__autoBracket ||
        event.inputType !== "insertText" || !event.data) {
      return;
    }
    const char = event.data;
    const context = this.caretContext(char);
    // The same mark already sits right after the caret: step over it instead of
    // pairing again (auto-paired closers, and the ` that closes `code`).
    if (context && context.next === char && this.CLOSERS.includes(char)) {
      event.preventDefault();
      const range = document.createRange();
      range.setStart(context.node, context.at + 1);
      range.collapse(true);
      const selection = getSelection();
      selection.removeAllRanges(); selection.addRange(range);
      // The pair is now complete: render any inline mark it closed.
      requestAnimationFrame(() => {
        const host = this.selectionElement()?.closest?.("h1,h2,h3,h4,h5,h6,p,blockquote");
        if (host && !host.closest(".md-code,table,.md-atom,li")) this.liveFormat(host);
      });
      return;
    }
    if (!(char in this.PAIRS)) {
      return;
    }
    // A backtick continuing a run of two or more types a fence, not inline code.
    // Insert it literally so ```python stays a bare fence and Enter can convert it
    // into a code block with that language.
    if (char === "\x60" && context && context.run >= 2) {
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
    this.wrapSelection(open,close);
  },

  loadSurface() {
    this.surfaceReady = false;
    this.languagePicker?.close();
    // The rebuild replaces every atom element; any lingering edit reference
    // pointed at a detached node and would otherwise swallow later input.
    this.activeAtom = null;
    return Promise.resolve(this.bridge.loadSurfaceHtml())
      .then((raw) => {
        const html = JSON.parse(raw);
        const doc = document.getElementById("doc");
        doc.contentEditable = "true";
        // Disconnect lazy-highlight observers before replacing the DOM so
        // repeated surface rebuilds don't accumulate IntersectionObservers.
        doc.querySelectorAll(".md-code").forEach((b) => b._codeObserver?.disconnect());
        doc.innerHTML = html;
        this.wrapInlineMath(doc);
        this.postProcess(doc);
        this.surfaceReady = true;
      })
      .catch((error) => {
        window.__loadErr = String(error && error.message || error);
      });
  },

  // Set up persistent code editors and render Mermaid atoms.
  postProcess(doc) {
    // setupCode installs an IntersectionObserver that highlights a block
    // only when it nears the viewport, so a long document does not run
    // Pygments over every code block on each (re)render. Highlight the
    // first few (above-the-fold) blocks immediately so opening a document
    // shows colored code without waiting for an observer callback.
    const codeBlocks = doc.querySelectorAll(".md-code");
    codeBlocks.forEach((block, index) => {
      this.setupCode(block);
      if (index < App.CODE_HIGHLIGHT_HEAD) {
        this.refreshCode(block);
        block._codeObserver?.disconnect();
        block._codeObserver = null;
      }
    });
    this.applyCodePrefs();
    doc.querySelectorAll("table").forEach(table=>table.title="Ctrl+Enter 新增行 · Alt+Enter 新增列 · Tab 下一个单元格");
    // Task checkboxes are enabled for display; toggling is handled once by
    // the capture-phase mousedown delegation (onMouseDown), which survives
    // surface rebuilds without per-element rebinding.
    doc.querySelectorAll("input.task-checkbox").forEach((cb)=>{
      cb.removeAttribute("disabled");
      cb.setAttribute("tabindex", "-1");
    });
    this.renderMath();
    this.updateHeadingHint();
  },

  // Wrap literal $...$ in text nodes of opened/pasted prose as math-inline
  // spans without disturbing already-rendered elements (strong, links…).
  wrapInlineMath(root) {
    const MATH = /(?<![\\$])\$([^\s$][^$]*?[^\s$]|[^\s$])\$(?!\w)/;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const el = node.parentElement;
        if (!el || !/\$/.test(node.nodeValue)) return NodeFilter.FILTER_REJECT;
        if (el.closest("code,pre,.md-atom,.math-inline,a,script,style")) {
          return NodeFilter.FILTER_REJECT;
        }
        return MATH.test(node.nodeValue)
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const targets = [];
    let current = walker.nextNode();
    while (current) { targets.push(current); current = walker.nextNode(); }
    targets.forEach((textNode) => {
      const fragment = document.createDocumentFragment();
      let rest = textNode.nodeValue;
      while (rest) {
        const m = MATH.exec(rest);
        if (!m) { fragment.appendChild(document.createTextNode(rest)); break; }
        if (m.index > 0) fragment.appendChild(document.createTextNode(rest.slice(0, m.index)));
        const span = document.createElement("span");
        span.className = "math-inline";
        span.dataset.tex = m[1];
        span.textContent = m[1];
        fragment.appendChild(span);
        rest = rest.slice(m.index + m[0].length);
      }
      textNode.replaceWith(fragment);
    });
  },

  // Render math with KaTeX. Block atoms carry source in data-md; inline
  // spans carry TeX in data-tex (which the serializer always prefers, so
  // replacing their visual content cannot corrupt the saved Markdown).
  renderMath() {
    if (!window.katex) return;
    document.querySelectorAll(".atom-math").forEach((atom) => {
      if (this.editingAtom() === atom) return; // shown as source while editing
      const render = atom.querySelector(".math-render");
      if (!render || render.dataset.rendered) return;
      const raw = (atom.dataset.md || "").trim();
      const body = raw.replace(/^\$\$\s?/, "").replace(/\s?\$\$$/, "");
      try {
        window.katex.render(body, render, {
          displayMode: true, throwOnError: false, output: "html",
        });
        render.dataset.rendered = "1";
        atom.querySelector(".math-source")?.setAttribute("hidden", "");
        render.removeAttribute("hidden");
      } catch (error) {
        render.textContent = body;
      }
    });
    document.querySelectorAll(".math-inline").forEach((span) => {
      if (span.dataset.rendered) return;
      const tex = span.dataset.tex != null ? span.dataset.tex : span.textContent;
      try {
        window.katex.render(tex, span, {
          displayMode: false, throwOnError: false, output: "html",
        });
        span.dataset.rendered = "1";
      } catch (error) { /* leave literal TeX visible */ }
    });
  },

  // ------------------------------------------------ sync -------------------

  scheduleSync() {
    if (this.syncTimer) clearTimeout(this.syncTimer);
    this.syncTimer = setTimeout(() => this.pushSurface(), 120);
  },

  pushSurface() {
    const md = this.captureMarkdown();
    this.bridge.updateSurfaceText(md);
  },

  captureMarkdown() {
    if(this.syncTimer){clearTimeout(this.syncTimer);this.syncTimer=null;}
    const atom=this.editingAtom();
    if(atom) atom.dataset.md=atom.textContent;
    return HtmlToMd.serialize(document.getElementById("doc"));
  },

  onInput(event) {
    if(event?.target.closest?.(".md-code-tools")) return;
    const area=event?.target.closest?.(".md-code-area");
    if(area) {
      this.refreshCode(area.closest(".md-code"));
      // Observable marker for tests: a real input event reached the page.
      window.__mdLastInput = performance.now();
    }
    const atom=this.editingAtom();
    if(atom){
      // Atom input is real pending input: keep its source in sync (debounced
      // like prose keystrokes) so dirty state, autosave and exports see it.
      atom.dataset.md=atom.textContent;
      this.scheduleSync();
      return; // atom edits never trigger prose block conversion
    }
    this.scheduleSync();
    // While an IME composition is active the DOM must not be rebuilt:
    // replacing the text node being composed (block conversion, inline
    // reformat) breaks the IME anchor — the first pinyin letters land raw in
    // English and following keystrokes get lost. Defer until compositionend.
    if (event.isComposing) return;
    // Convert immediately (synchronous) so markers never linger.
    this.formatCurrentBlock(event.data);
    this.updateFenceSuggestions();
    this.scheduleHint();
  },

  onCompositionEnd(event) {
    const target = event.target;
    if (!target || !target.closest ||
        !document.getElementById("doc").contains(target)) return;
    if (this.editingAtom() || target.closest(".md-code-area")) return;
    // Run the conversions skipped during composition against the settled text.
    this.formatCurrentBlock(event.data);
    this.scheduleHint();
  },

  // Characters that can CLOSE an inline mark; only they trigger an inline
  // re-render (Typora keeps raw markdown visible while you type the inside).
  INLINE_CLOSERS: new Set(["*", "_", "~", "`", ")", "]", "$"]),

  // Find the prose block the caret is currently in and convert it.
  formatCurrentBlock(typed) {
    const target = this.selectionElement();
    // Browsers create <div> when exiting a list via Enter; treat div as prose
    // too, but never treat #doc itself or structural wrappers as a block.
    const host = target && target.closest
      ? target.closest("h1,h2,h3,h4,h5,h6,p,blockquote,div")
      : null;
    if (!host || host.id === "doc" ||
        host.closest(".md-code, table, .md-atom, li, ul, ol")) return;
    // Block markers convert immediately; inline marks only when the typed
    // character can close one (or when pasting multiple characters).
    const shouldInline = (typeof typed === "string" && typed.length > 1)
      || (typed && this.INLINE_CLOSERS.has(typed));
    this.formatHost(host, shouldInline);
  },

  // Run inline + structural conversion for one host; returns the (possibly
  // replaced) element that now owns the text.
  formatHost(host, allowInline) {
    if (!host || !host.isConnected) return host;
    // Block conversion first: it builds the new element with already
    // formatted inline content.
    const converted = this.tryConvertBlock(host);
    if (converted) return converted;
    if (allowInline) this.liveFormat(host);
    return host;
  },

  // If a prose block starts with block Markdown, convert it in place. Built in
  // JS (not the Python engine) because a single fragment without surrounding
  // blank lines is treated as a plain paragraph by Markdown.
  // Returns the new element when converted, otherwise null.
  tryConvertBlock(host) {
    if (host.tagName === "LI") return null; // already a list item
    // Normalize non-breaking spaces (browsers keep typed trailing
    // spaces as &nbsp;) so a marker followed by nbsp still converts.
    const text = host.textContent.replace(/ /g, " ");
    let m;
    let tag = null, inner = text, isList = false, ordered = false;
    if ((m = /^\s{0,3}(#{1,6})[ \t ]+([\s\S]*)$/.exec(text))) {
      tag = "h" + m[1].length; inner = m[2];
    } else if ((m = /^\s{0,3}>[ \t ]?([\s\S]*)$/.exec(text))) {
      tag = "blockquote"; inner = m[1];
    } else if ((m = /^\s{0,3}[-+*][ \t ]+([\s\S]*)$/.exec(text))) {
      tag = "ul"; isList = true;
    } else if ((m = /^\s{0,3}\d{1,9}[.)][ \t ]+([\s\S]*)$/.exec(text))) {
      tag = "ol"; isList = true; ordered = true;
    } else if (/^\s{0,3}(?:-{3,}|\*{3,}|_{3,})[ \t ]*$/.test(text)) {
      tag = "hr";
    }
    if (!tag) return null;
    // Caret offset within the block before replacement (plain-text length).
    const caret = this.caretOffsetIn(host);
    const markerLen = text.length - inner.length;
    const newCaret = Math.max(0, caret - markerLen);

    let replacement;
    if (tag === "hr") {
      replacement = document.createElement("hr");
    } else if (isList) {
      replacement = document.createElement(tag);
      const li = document.createElement("li");
      li.innerHTML = MdInline.format(ordered ? m[1] : m[1]) || "<br>";
      replacement.appendChild(li);
    } else if (tag === "blockquote") {
      replacement = document.createElement("blockquote");
      const p = document.createElement("p");
      p.innerHTML = MdInline.format(inner) || "<br>";
      replacement.appendChild(p);
    } else {
      replacement = document.createElement(tag);
      replacement.innerHTML = MdInline.format(inner) || "<br>";
    }
    host.replaceWith(replacement);
    const focusTarget = isList ? replacement.querySelector("li")
      : tag === "blockquote" ? replacement.querySelector("p")
      : tag === "hr" ? null : replacement;
    if (focusTarget) this.restoreCaret(focusTarget, newCaret);
    this.postProcess(document.getElementById("doc"));
    this.scheduleSync();
    return replacement;
  },

  caretOffsetIn(host) {
    const selection = getSelection();
    if (!selection.rangeCount) return host.textContent.length;
    const probe = document.createRange();
    probe.selectNodeContents(host);
    try {
      probe.setEnd(selection.anchorNode, selection.anchorOffset);
      return probe.toString().length;
    } catch (error) {
      return host.textContent.length;
    }
  },

  // Convert inline marks inside one prose block while keeping the caret stable.
  liveFormat(host) {
    if (!host || !host.isConnected) return;
    // A KaTeX-rendered math span owns its inner DOM; re-running text-level
    // formatting over its content would garble the formula (its textContent
    // mixes MathML and visual spans). Such a line is considered settled.
    if (host.querySelector(".math-inline[data-rendered='1']")) return;
    // Settled escape-literal spans (e.g. \*) own their source too; rebuilding
    // from textContent would drop the backslash and could turn "*" italic.
    if (host.querySelector(".md-literal")) return;
    const before = host.textContent;
    if (!/[`*_~$]|\]\(/.test(before)) return;
    const caret = this.caretOffsetIn(host);
    const html = MdInline.format(before);
    if (html === host.innerHTML) return;
    host.innerHTML = html;
    this.restoreCaret(host, caret);
    this.scheduleSync();
  },

  // Place the caret at the given plain-text offset within an element.
  restoreCaret(root, offset) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    let remaining = Math.max(0, offset);
    while (node) {
      if (remaining <= node.length) {
        const range = document.createRange();
        range.setStart(node, remaining);
        range.collapse(true);
        const selection = getSelection();
        selection.removeAllRanges(); selection.addRange(range);
        return;
      }
      remaining -= node.length;
      node = walker.nextNode();
    }
    // Offset past the end: collapse to end.
    const range = document.createRange();
    range.selectNodeContents(root); range.collapse(false);
    const selection = getSelection();
    selection.removeAllRanges(); selection.addRange(range);
  },

  // Wrap the current selection in inline marks; with no selection insert a pair.
  wrapSelection(before, after) {
    const selection=getSelection();
    if(!selection.rangeCount) return;
    const text=selection.toString();
    document.execCommand("insertText",false,before+text+after);
    const node=selection.anchorNode, end=selection.anchorOffset-after.length;
    if(node?.nodeType===3) {
      const range=document.createRange();
      range.setStart(node,Math.max(0,end-text.length));
      range.setEnd(node,Math.max(0,end));
      selection.removeAllRanges();selection.addRange(range);
    }
    this.scheduleSync();
  },

  caretRange(root, offset) {
    const range=document.createRange();
    const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    let node=root.nodeType===3?root:walk.nextNode();
    let last=null;
    while(node){if(offset<=node.length){range.setStart(node,Math.max(0,offset));range.collapse(true);return range;}offset-=node.length;last=node;node=walk.nextNode();}
    if(last) range.setStart(last,last.length);else range.setStart(root,0);
    range.collapse(true);return range;
  },

  insertLink() {
    const text = getSelection().toString() || "链接文字";
    this.wrapSelection("[", "](https://)");
  },

  // Find the rendered element (and an editable inner node) for a model index.
  locateBlock(index) {
    const doc = document.getElementById("doc");
    const child = doc.querySelector('[data-model-index="' + index + '"]')
      || doc.children[Math.max(0, index)];
    if (!child) return null;
    const focusable = child.matches("h1,h2,h3,h4,h5,h6,p,li,blockquote")
      ? child : (child.querySelector("h1,h2,h3,h4,h5,h6,p,li,blockquote") || child);
    return { child, focusable };
  },

  // Scroll the block at the given model block index into view (surface children
  // follow the block order, including the trailing end block).
  jumpToBlock(index) {
    const located = this.locateBlock(index);
    if (!located) return;
    located.child.scrollIntoView({ block: "start" });
    const range = document.createRange();
    range.selectNodeContents(located.focusable); range.collapse(true);
    const selection = getSelection();
    selection.removeAllRanges(); selection.addRange(range);
  },

  // Search-result jump: model block index plus an in-block text offset.
  jumpToLine(index, offset = 0) {
    const located = this.locateBlock(index);
    if (!located) return JSON.stringify({ found: false });
    located.child.scrollIntoView({ block: "start" });
    const range = this.caretRange(located.focusable, Math.max(0, offset | 0));
    range.collapse(true);
    const selection = getSelection();
    selection.removeAllRanges(); selection.addRange(range);
    return JSON.stringify({ found: true });
  },

  // Model index of the block owning the current caret (F2 "edit block source").
  get activeIndex() {
    const node = this.selectionElement();
    const host = node && node.closest && node.closest("[data-model-index]");
    return host ? Number(host.dataset.modelIndex) : 0;
  },

  // Put the caret into (or open the source editor of) the block at `index`.
  switchTo(index, options = {}) {
    const located = this.locateBlock(index);
    if (!located) return;
    located.child.scrollIntoView({ block: "start" });
    const atom = (located.child.classList && located.child.classList.contains("md-atom"))
      ? located.child : (located.child.querySelector && located.child.querySelector(".md-atom"));
    if (atom && !this.editingAtom()) {
      this.editAtom(atom);
      return;
    }
    const code = (located.child.classList && located.child.classList.contains("md-code"))
      ? located.child : (located.child.querySelector && located.child.querySelector(".md-code"));
    if (code) {
      const area = code.querySelector(".md-code-area");
      if (area) {
        this.selectOffsets(area, Number(options.caret) || 0);
        area.focus();
        return;
      }
    }
    const range = this.caretRange(located.focusable, Number(options.caret) || 0);
    range.collapse(true);
    const selection = getSelection();
    selection.removeAllRanges(); selection.addRange(range);
  },

  // Native window.find leaves no persistent highlight; drop its selection.
  clearDocumentFind() {
    try { getSelection().removeAllRanges(); } catch (_) { /* no selection yet */ }
  },

  // Toggle the task checkbox of the current list item; in a plain item insert
  // one; elsewhere convert the current block into a task item.
  toggleCurrentTask() {
    const host = this.selectionElement();
    const li = host && host.closest && host.closest("#doc li");
    if (li) {
      let cb = (li.querySelector && li.querySelector(":scope > input.task-checkbox"))
        || li.querySelector("input.task-checkbox");
      if (cb) {
        const now = !cb.hasAttribute("checked");
        cb.toggleAttribute("checked", now);
        cb.checked = now;
      } else {
        cb = document.createElement("input");
        cb.type = "checkbox";
        cb.className = "task-checkbox";
        cb.setAttribute("tabindex", "-1");
        li.insertBefore(cb, li.firstChild);
      }
      this.scheduleSync();
      return;
    }
    const block = host && host.closest
      && host.closest("h1,h2,h3,h4,h5,h6,p,blockquote");
    if (!block || block.closest(".md-code,table,.md-atom")) return;
    const caret = this.caretOffsetIn(block);
    const ul = document.createElement("ul");
    const item = document.createElement("li");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "task-checkbox";
    cb.setAttribute("tabindex", "-1");
    item.appendChild(cb);
    while (block.firstChild) item.appendChild(block.firstChild);
    ul.appendChild(item);
    block.replaceWith(ul);
    this.postProcess(document.getElementById("doc"));
    this.restoreCaret(item, caret);
    this.scheduleSync();
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
    const copy=document.getElementById("doc").cloneNode(true);
    copy.querySelectorAll(".md-code-tools,.md-code-highlight,.md-code-numbers,.md-code-lang").forEach(n=>n.remove());
    const body = copy.textContent;
    if (!text) return 0;
    const lower = body.toLowerCase(), q = text.toLowerCase();
    let count = 0, at = 0;
    while ((at = lower.indexOf(q, at)) >= 0) { count += 1; at += q.length; }
    return count;
  },

  // ------------------------------------------------ atoms ------------------

  onClick(event) {
    const preview=event.target.closest?.(".md-diagram-preview");
    if(preview) {
      event.preventDefault();
      const block=preview.closest(".md-code");
      this.setDiagramEditing(block,true);
      block.querySelector(".md-code-area").focus();
      return;
    }
    const link = event.target.closest?.("a[href]");
    if (link) {
      event.preventDefault();
      const href = link.getAttribute("href");
      if (href.startsWith("#")) {
        try { document.getElementById(decodeURIComponent(href.slice(1)))?.scrollIntoView({block:"start"}); }
        catch (_) { /* A malformed fragment does not navigate the editor. */ }
      } else this.bridge.openExternal(href);
      return;
    }
    const cell=event.target.closest?.("th,td");
    if(cell) this.lastTableCell=cell;
    const atom = event.target.closest && event.target.closest(".md-atom");
    if (atom && !this.editingAtom()) {
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
    const atom = this.editingAtom();
    if (!atom) return;
    // Keep the source even when unchanged so Esc can restore mdBefore after
    // the debounced live sync (atom input updates data-md immediately).
    atom.setAttribute("data-md", apply ? atom.textContent : atom.dataset.mdBefore);
    this.activeAtom = null;
    this.pushSurface(); // settle the model before rebuilding the surface
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

  languageOption(value,label) {
    const item=document.createElement("button");item.type="button";
    item.className="md-code-lang-item";item.dataset.value=value;
    item.setAttribute("role","option");item.tabIndex=-1;
    const icon=document.createElement("span");icon.className="md-code-lang-icon";
    icon.setAttribute("aria-hidden","true");
    icon.textContent=['mermaid','plantuml','dot','d2','nomnoml'].includes(value)?"◇":
      ['json','json5','yaml','toml','sql','mysql','mariadb','postgresql','sqlite3','mongodb','cassandra'].includes(value)?"▤":"‹›";
    const name=document.createElement("span");name.textContent=label;item.append(icon,name);
    return item;
  },

  updateFenceSuggestions() {
    const paragraph=this.selectionElement()?.closest("p");
    const match=paragraph && !paragraph.closest(".md-code,table,.md-atom") &&
      paragraph.textContent.match(/([\s\S]*?)(\x60{3,}|~{3,})([\w+#.-]*)$/);
    if(!match || this.textOffset(paragraph)!==paragraph.textContent.length) {
      this.fenceCompletion?.menu.close();return;
    }
    this.languagePicker?.close();
    const menu=document.createElement("div");
    menu.className="md-code-lang-list md-fence-lang-list";menu.setAttribute("role","listbox");
    menu.setAttribute("aria-label","代码块语言建议");
    const state={paragraph,match,menu,active:-1};
    menu.close=()=>{
      menu.remove();if(this.fenceCompletion===state) this.fenceCompletion=null;
      if(this.languagePicker===menu) this.languagePicker=null;
    };
    this.languagePicker=menu;this.fenceCompletion=state;
    CodeEditing.suggestions(match[3]).forEach(([value,label])=>{
      const item=this.languageOption(value,label);
      item.addEventListener("mousedown",event=>{
        event.preventDefault();menu.close();this.insertFenceCode(paragraph,match,value);
      });
      menu.append(item);
    });
    if(!menu.children.length) {menu.close();return;}
    document.body.append(menu);
    const range=getSelection().getRangeAt(0).cloneRange();range.collapse(false);
    const rect=range.getBoundingClientRect(), fallback=paragraph.getBoundingClientRect();
    const top=rect.height?rect.bottom:fallback.bottom;
    menu.style.left=Math.max(8,Math.min(rect.height?rect.left:fallback.left,innerWidth-menu.offsetWidth-12))+"px";
    const below=innerHeight-top-12, above=(rect.height?rect.top:fallback.top)-12;
    menu.style.maxHeight=Math.min(288,Math.max(80,above>below&&below<240?above:below))+"px";
    menu.style.top=(below<240&&above>below?Math.max(8,top-menu.offsetHeight-(rect.height||24)-4):top+4)+"px";
  },

  insertFenceCode(paragraph,match,language) {
    const range=document.createRange();
    if(match[1]) {
      const start=this.caretRange(paragraph,match[1].length);
      const tail=this.caretRange(paragraph,paragraph.textContent.length);
      range.setStart(start.startContainer,start.startOffset);
      range.setEnd(tail.startContainer,tail.startOffset);
    } else range.selectNode(paragraph);
    const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
    this.insertMarkdown(match[2]+language+"\n\n"+match[2]);
  },

  selectionElement() {
    const node = getSelection().anchorNode;
    return node && (node.nodeType === 1 ? node : node.parentElement);
  },

  offsets(area) {
    const selection = getSelection();
    if (!selection.rangeCount) return {start:0,end:0};
    const selected = selection.getRangeAt(0);
    const prefix = document.createRange();
    prefix.selectNodeContents(area);
    prefix.setEnd(selected.startContainer, selected.startOffset);
    const start = prefix.toString().length;
    prefix.setEnd(selected.endContainer, selected.endOffset);
    return {start,end:prefix.toString().length};
  },

  selectOffsets(area, start, end=start) {
    const range = this.caretRange(area,start);
    const last = this.caretRange(area,end);
    range.setEnd(last.startContainer,last.startOffset);
    const selection=getSelection();
    selection.removeAllRanges(); selection.addRange(range);
  },

  applyCodeEdit(area, edit) {
    if (!edit) return;
    if (edit.skip !== undefined) { this.selectOffsets(area,edit.skip); return; }
    this.selectOffsets(area,edit.start,edit.end);
    if(edit.text.includes("\n")) {
      const escaped=document.createElement("span");escaped.textContent=edit.text;
      document.execCommand("insertHTML",false,escaped.innerHTML);
    } else document.execCommand("insertText",false,edit.text);
    this.selectOffsets(area,edit.caret,edit.selectionEnd ?? edit.caret);
    this.refreshCode(area.closest(".md-code"));
    this.scheduleSync();
  },

  applyCodePrefs() {
    document.querySelectorAll(".md-code").forEach(block=>{
      block.classList.toggle("has-line-numbers",!!window.__codeLineNumbers);
      block.style.setProperty("--tab-size",window.__tabSize||2);
    });
    this.renderDiagrams();
  },

  renderDiagrams() {
    document.querySelectorAll(".md-code").forEach(block=>this.refreshDiagram(block));
  },

  setDiagramEditing(block, editing) {
    block.classList.toggle("is-diagram-editing",editing);
    block.classList.toggle("diagram-preview-only",!editing);
    if(block._diagramToggle) {
      block._diagramToggle.textContent=editing?"预览图表":"编辑源码";
      block._diagramToggle.setAttribute("aria-expanded",String(editing));
    }
    if(!editing) this.refreshDiagram(block,true);
  },

  refreshDiagram(block, immediate=false) {
    const enabled=CodeEditing.language(block.dataset.lang)==="mermaid" && window.__mermaid!==false;
    block.classList.toggle("atom-diagram",CodeEditing.language(block.dataset.lang)==="mermaid");
    block.classList.toggle("has-diagram",enabled);
    if(!enabled) {
      clearTimeout(block._diagramTimer);
      block._diagramRevision=(block._diagramRevision||0)+1;
      block._diagramSource=null;
      block._diagramPreview?.replaceChildren();
      block.classList.remove("diagram-preview-only","is-diagram-editing","diagram-invalid");
      if(block._diagramToggle) block._diagramToggle.hidden=true;
      return;
    }
    if(!block._diagramPreview) {
      const preview=document.createElement("div");
      preview.className="md-diagram-preview mermaid";
      preview.setAttribute("role","button");preview.tabIndex=0;
      preview.setAttribute("aria-label","Mermaid 图表，点击编辑源码");
      preview.addEventListener("keydown",event=>{
        if(event.key==="Enter"||event.key===" ") {
          event.preventDefault();event.stopPropagation();preview.click();
        }
      });
      block.append(preview);block._diagramPreview=preview;
      const toggle=document.createElement("button");
      toggle.type="button";toggle.className="md-diagram-toggle";
      toggle.addEventListener("mousedown",event=>event.preventDefault());
      toggle.addEventListener("click",()=>{
        const editing=!block.classList.contains("is-diagram-editing");
        this.setDiagramEditing(block,editing);
        if(editing) block.querySelector(".md-code-area").focus();
        else {block._diagramPreview.focus();this.pushSurface();}
      });
      block.querySelector(".md-code-tools").append(toggle);block._diagramToggle=toggle;
      block.querySelector(".md-code-area").addEventListener("focus",()=>{
        if(block.classList.contains("has-diagram")) this.setDiagramEditing(block,true);
      });
      block.addEventListener("focusout",()=>setTimeout(()=>{
        if(block.isConnected && !block.contains(document.activeElement) && block.classList.contains("has-diagram"))
          this.setDiagramEditing(block,false);
      },0));
      // Initialize the view without recursing into the renderer.
      const editing=block.contains(document.activeElement);
      block.classList.toggle("is-diagram-editing",editing);
      block.classList.toggle("diagram-preview-only",!editing);
      toggle.textContent=editing?"预览图表":"编辑源码";
      toggle.setAttribute("aria-expanded",String(editing));
    }
    block._diagramToggle.hidden=false;
    const source=HtmlToMd.codeText(block.querySelector(".md-code-area"));
    if(block._diagramSource===source) {
      if(immediate && block._diagramTimer) {
        clearTimeout(block._diagramTimer);block._diagramTimer=null;block._diagramRender?.();
      }
      return;
    }
    block._diagramSource=source;
    clearTimeout(block._diagramTimer);
    const revision=(block._diagramRevision||0)+1;
    block._diagramRevision=revision;
    const preview=block._diagramPreview;
    preview.setAttribute("aria-busy","true");
    const current=()=>block.isConnected && block._diagramRevision===revision &&
      block.classList.contains("has-diagram");
    const showError=message=>{
      if(!current()) return;
      preview.replaceChildren();
      const status=document.createElement("div");
      status.className="diagram-error";status.setAttribute("role","status");
      status.textContent=message;preview.append(status);
      preview.setAttribute("aria-busy","false");block.classList.add("diagram-invalid");
      block.dataset.rendered="error";
    };
    const render=async()=>{
      block._diagramTimer=null;
      if(!current()) return;
      if(!source.trim()) {showError("输入 Mermaid 源码后将在这里显示图表。");return;}
      if(!window.mermaid) {showError("Mermaid 组件未加载，请重新打开文档。");return;}
      try {
        if(!this.mermaidReady) {
          window.mermaid.initialize({startOnLoad:false,securityLevel:"strict",theme:"neutral",
            suppressErrorRendering:true});
          this.mermaidReady=true;
        }
        const id="md-diagram-"+(this.diagramSequence=(this.diagramSequence||0)+1);
        const result=await window.mermaid.render(id,source);
        if(!current()) return;
        preview.innerHTML=result.svg;
        result.bindFunctions?.(preview);
        block.classList.remove("diagram-invalid");block.dataset.rendered="1";
        preview.setAttribute("aria-busy","false");
      } catch(error) {
        showError("图表语法有误，请修改源码。\n"+String(error?.message||error).slice(0,500));
      }
    };
    block._diagramRender=render;
    if(immediate) render();
    else block._diagramTimer=setTimeout(render,350);
  },

  setupCode(block) {
    const area=block.querySelector(".md-code-area");
    const tools=block.querySelector(".md-code-tools");
    if (!area || !tools || tools.children.length) return;
    // Language combobox: type to filter (c -> C, C++, C#), click to pick.
    const langWrap=document.createElement("span");
    langWrap.className="md-code-lang-picker";
    const input=document.createElement("input");
    input.type="text";
    input.className="md-code-language";
    input.setAttribute("aria-label","代码语言");
    input.setAttribute("role","combobox");
    input.setAttribute("aria-autocomplete","list");
    input.setAttribute("aria-expanded","false");
    input.spellcheck=false;
    input.autocomplete="off";
    const cur=block.dataset.lang||"";
    input.value=cur;
    input.placeholder="选择语言…";
    input.title="输入语言（如 c 联想 C/C++/C#），或点击选择";
    const list=document.createElement("div");
    list.className="md-code-lang-list";
    list.id="code-languages-"+(this.languageSequence=(this.languageSequence||0)+1);
    list.setAttribute("role","listbox");input.setAttribute("aria-controls",list.id);
    list.hidden=true;
    langWrap.append(input,list);

    const close=()=>{
      list.hidden=true; input.setAttribute("aria-expanded","false");
      input.removeAttribute("aria-activedescendant");block.classList.remove("language-picker-open");
      if(this.languagePicker===langWrap) this.languagePicker=null;
    };
    langWrap.close=close;
    let active=-1;
    const activate=index=>{
      const items=[...list.querySelectorAll(".md-code-lang-item")];
      if(!items.length) return;
      active=(index+items.length)%items.length;
      items.forEach((item,i)=>item.setAttribute("aria-selected",String(i===active)));
      input.setAttribute("aria-activedescendant",items[active].id);
      items[active].scrollIntoView({block:"nearest"});
    };

    const applyLanguage=(value)=>{
      const normalized=CodeEditing.language(value||"");
      block.dataset.lang=normalized;
      block.querySelector(".md-code-lang").textContent=normalized||"text";
      input.value=normalized;
      close();
      this.refreshCode(block); this.pushSurface();
    };
    const renderList=(filter)=>{
      this.languagePicker?.close();this.languagePicker=langWrap;
      const matches=CodeEditing.suggestions(filter);
      list.innerHTML="";
      active=-1;
      matches.forEach(([value,label],index)=>{
        const item=this.languageOption(value,label);
        item.id=list.id+"-"+index;
        item.setAttribute("aria-selected","false");
        // Mouse selection (mousedown fires before the input loses focus).
        item.addEventListener("mousedown",(e)=>{
          e.preventDefault();
          applyLanguage(value);
          area.focus();
        });
        item.addEventListener("click",()=>{applyLanguage(value);area.focus();});
        list.appendChild(item);
      });
      if(!matches.length) {
        const empty=document.createElement("div");empty.className="md-code-lang-empty";
        empty.textContent="无匹配项，按 Enter 使用自定义语言";list.append(empty);
      }
      list.hidden=false;
      block.classList.add("language-picker-open");input.setAttribute("aria-expanded","true");
      const rect=input.getBoundingClientRect(), below=innerHeight-rect.bottom-12, above=rect.top-12;
      const upwards=below<240 && above>below;
      list.classList.toggle("opens-up",upwards);
      list.style.maxHeight=Math.min(288,Math.max(80,upwards?above:below))+"px";
    };
    input.addEventListener("input",()=>renderList(input.value));
    input.addEventListener("focus",()=>{input.select();renderList("");});
    input.addEventListener("click",()=>{if(list.hidden) renderList("");});
    langWrap.addEventListener("focusout",()=>setTimeout(()=>{
      if(!langWrap.contains(document.activeElement)) close();
    },0));
    input.addEventListener("keydown",(e)=>{
      e.stopPropagation();
      if(e.isComposing || e.keyCode===229) return;
      if(e.key==="Enter"){
        e.preventDefault();
        const items=list.querySelectorAll(".md-code-lang-item");
        const exact=CodeEditing.languages.find(([value])=>value===CodeEditing.language(input.value));
        applyLanguage(active>=0?items[active].dataset.value:exact?exact[0]:items[0]?.dataset.value??input.value);
        area.focus();
      }else if(e.key==="Escape"){
        e.preventDefault();input.value=block.dataset.lang||"";close();area.focus();
      }else if(e.key==="ArrowDown"||e.key==="ArrowUp"){
        e.preventDefault();if(list.hidden) renderList("");
        activate(active<0?(e.key==="ArrowDown"?0:-1):active+(e.key==="ArrowDown"?1:-1));
      }else if(e.key==="Tab"){
        if(active>=0) applyLanguage(list.querySelectorAll(".md-code-lang-item")[active].dataset.value);
        close();
      }
    });
    input.addEventListener("change",()=>applyLanguage(input.value));

    const hint=document.createElement("span");
    hint.className="md-code-hint";hint.textContent="Tab 缩进 · Ctrl+Enter 退出";
    const copy=document.createElement("button");
    copy.className="md-code-copy";
    copy.type="button";copy.textContent="复制";copy.title="复制代码正文";
    copy.addEventListener("mousedown",event=>event.preventDefault());
    copy.addEventListener("click",()=>{
      const selection=getSelection(), saved=selection.rangeCount?selection.getRangeAt(0).cloneRange():null;
      const active=document.activeElement, clipboard=document.createElement("textarea");
      clipboard.value=HtmlToMd.codeText(area);clipboard.readOnly=true;
      clipboard.style.cssText="position:fixed;left:-10000px;top:0";
      document.body.append(clipboard);clipboard.select();
      const ok=document.execCommand("copy");clipboard.remove();active?.focus();
      if(saved){selection.removeAllRanges();selection.addRange(saved);}
      copy.textContent=ok?"已复制":"复制";setTimeout(()=>copy.textContent="复制",1000);
    });
    tools.append(langWrap,hint,copy);
    const numbers=document.createElement("pre");
    numbers.className="md-code-numbers";numbers.setAttribute("aria-hidden","true");
    area.parentElement.prepend(numbers);

    // Lazy syntax highlighting: highlight once when the block scrolls near
    // the viewport. The block shows plain monospaced text until then, which
    // keeps initial render of huge documents off the main thread.
    if ("IntersectionObserver" in window && !block._codeObserver) {
      block._codeObserver = new IntersectionObserver((entries, obs) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            this.refreshCode(block);
            obs.unobserve(block);
            block._codeObserver = null;
          }
        }
      }, { root: null, rootMargin: "600px 0px" });
      block._codeObserver.observe(block);
    } else {
      this.refreshCode(block);
    }
  },

  refreshCode(block) {
    if (!block) return;
    this.refreshDiagram(block);
    const area=block.querySelector(".md-code-area");
    const mirror=block.querySelector(".md-code-highlight");
    const text=HtmlToMd.codeText(area), language=block.dataset.lang||"";
    if(block._highlightSource===text && block._highlightLanguage===language) return;
    block._highlightSource=text;block._highlightLanguage=language;
    block.querySelector(".md-code-numbers").textContent=
      Array.from({length:text.split("\n").length},(_,i)=>i+1).join("\n");
    // Render a plain mirror immediately; never replace the editable DOM.
    mirror.textContent=text+"\n";
    const revision=(block._highlightRevision||0)+1;
    block._highlightRevision=revision;
    clearTimeout(block._highlightTimer);
    block._highlightTimer=setTimeout(()=>{
      Promise.resolve(this.bridge.highlightCode(block.dataset.lang||"",text)).then(html=>{
        if(block.isConnected && block._highlightRevision===revision) mirror.innerHTML=html+"\n";
      }).catch(()=>{ /* the plain mirror remains usable */ });
    },70);
  },

  onCodeKeyDown(event, area) {
    if(event.isComposing || event.keyCode===229) return;
    const ctrl=event.ctrlKey||event.metaKey;
    const {start,end}=this.offsets(area), text=HtmlToMd.codeText(area);
    const lang=area.closest(".md-code").dataset.lang||"";
    if(ctrl&&event.key.toLowerCase()==="a") {
      event.preventDefault();this.selectOffsets(area,0,text.length);return;
    }
    if(event.key==="Escape" || ctrl&&event.key==="Enter") {
      event.preventDefault();
      const block=area.closest(".md-code");
      if(block.classList.contains("has-diagram")) this.setDiagramEditing(block,false);
      let next=block.nextElementSibling;
      if(!next || next.contentEditable==="false") {
        next=document.createElement("p");next.innerHTML="<br>";block.after(next);
      }
      document.getElementById("doc").focus();
      const range=document.createRange();range.selectNodeContents(next);range.collapse(true);
      const s=getSelection();s.removeAllRanges();s.addRange(range);return;
    }
    let edit=null;
    if(event.key==="Enter"&&!event.altKey) edit=CodeEditing.newline(text,start,end,lang,window.__tabSize);
    if(event.key==="Tab"&&!ctrl&&!event.altKey) edit=CodeEditing.tab(text,start,end,lang,window.__tabSize,event.shiftKey);
    if(window.__autoBracket && event.key==="Backspace"&&start===end&&start>0 &&
      CodeEditing.pairs[text[start-1]]===text[start])
      edit={start:start-1,end:start+1,text:"",caret:start-1};
    if(edit){event.preventDefault();this.applyCodeEdit(area,edit);}
  },

  focusCell(cell) {
    if(!cell) return;
    document.getElementById("doc").focus();
    const range=document.createRange();range.selectNodeContents(cell);range.collapse(true);
    const s=getSelection();s.removeAllRanges();s.addRange(range);
    this.lastTableCell=cell;cell.scrollIntoView({block:"nearest",inline:"nearest"});
  },

  onTableKeyDown(event,cell) {
    if(event.key==="Enter"&&event.ctrlKey&&!event.altKey) {
      event.preventDefault();this.insertTableRow(cell);
    } else if(event.key==="Enter"&&event.altKey&&!event.ctrlKey) {
      event.preventDefault();this.insertTableColumn(cell);
    } else if(event.key==="Tab"&&!event.ctrlKey&&!event.altKey) {
      event.preventDefault();
      const cells=Array.from(cell.closest("table").querySelectorAll("th,td"));
      const next=cells[cells.indexOf(cell)+(event.shiftKey?-1:1)];
      if(next)this.focusCell(next);
      else if(!event.shiftKey)this.insertTableRow(cell,true);
    } else return;
    this.pushSurface();
  },

  editTable(cell,change) {
    const original=cell.closest("table"),copy=original.cloneNode(true);
    const coordinates=change(copy,cell.parentElement.rowIndex,cell.cellIndex);
    const token="edit-"+Date.now()+"-"+Math.random().toString(36).slice(2);
    copy.dataset.tableEdit=token;
    document.getElementById("doc").focus();
    const range=document.createRange();range.selectNode(original);
    const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
    // One native operation makes structure edits undoable as well as text.
    document.execCommand("insertHTML",false,copy.outerHTML);
    const inserted=document.querySelector('[data-table-edit="'+token+'"]');
    if(inserted) {
      inserted.removeAttribute("data-table-edit");
      this.focusCell(inserted.rows[coordinates[0]]?.cells[coordinates[1]]);
    }
  },

  insertTableRow(cell,firstColumn=false) {
    this.editTable(cell,(table,rowIndex,index)=>{
      const row=table.rows[rowIndex],tr=document.createElement("tr");
      Array.from(row.cells).forEach((old,i)=>{
        const fresh=document.createElement("td");
        fresh.style.textAlign=table.rows[0].cells[i].style.textAlign;
        fresh.appendChild(document.createElement("br"));tr.append(fresh);
      });
      if(row.closest("thead")) (table.tBodies[0]||table.createTBody()).prepend(tr);
      else row.after(tr);
      return [tr.rowIndex,firstColumn?0:index];
    });
  },

  insertTableColumn(cell) {
    this.editTable(cell,(table,rowIndex,index)=>{
      const alignment=table.rows[0].cells[index].style.textAlign;
      Array.from(table.rows).forEach(row=>{
        const fresh=document.createElement(row.closest("thead")?"th":"td");
        fresh.style.textAlign=alignment;fresh.appendChild(document.createElement("br"));
        row.insertBefore(fresh,row.cells[index+1]||null);
      });
      return [rowIndex,index+1];
    });
  },

  tableCommand(command) {
    const cell=this.selectionElement()?.closest("th,td")||this.lastTableCell;
    if(!cell || !cell.isConnected) return;
    if(command==="row") this.insertTableRow(cell);
    else if(command==="column") this.insertTableColumn(cell);
    else this.editTable(cell,(table,rowIndex,index)=>{
      const row=table.rows[rowIndex];
      if(["left","center","right"].includes(command))
        Array.from(table.rows).forEach(r=>r.cells[index].style.textAlign=command);
      else if(command==="deleteRow"&&!row.closest("thead")) {
        row.remove();rowIndex=Math.min(rowIndex,table.rows.length-1);
      } else if(command==="deleteColumn"&&row.cells.length>1) {
        Array.from(table.rows).forEach(r=>r.cells[index].remove());
        index=Math.min(index,row.cells.length-1);
      }
      return [rowIndex,index];
    });
    this.pushSurface();
  },

  focusEditor() {
    const area=this.selectionElement()?.closest(".md-code-area");
    (area||document.getElementById("doc")).focus();
  },

  undo() { document.execCommand("undo"); this.postProcess(document.getElementById("doc")); this.pushSurface(); },
  redo() { document.execCommand("redo"); this.postProcess(document.getElementById("doc")); this.pushSurface(); },

  insertMarkdown(markdown) {
    const area=this.selectionElement()?.closest(".md-code-area");
    if(area){const {start,end}=this.offsets(area);this.applyCodeEdit(area,{start,end,text:markdown,caret:start+markdown.length});this.pushSurface();return;}
    const saved=getSelection().rangeCount?getSelection().getRangeAt(0).cloneRange():null;
    Promise.resolve(this.bridge.renderMarkdown(markdown)).then(html=>{
      const doc=document.getElementById("doc");
      doc.focus();
      if(saved&&saved.startContainer.isConnected){const s=getSelection();s.removeAllRanges();s.addRange(saved);}
      else {const r=document.createRange();r.selectNodeContents(doc);r.collapse(false);const s=getSelection();s.removeAllRanges();s.addRange(r);}
      const fragment=document.createElement("div");fragment.innerHTML=html;
      const code=fragment.querySelector(".md-code"), table=fragment.querySelector("table");
      const token="insert-"+Date.now();
      if(code||table) (code||table).dataset.insertToken=token;
      document.execCommand("insertHTML",false,fragment.innerHTML);
      this.postProcess(doc);this.pushSurface();
      const inserted=doc.querySelector('[data-insert-token="'+token+'"]');
      if(inserted){
        inserted.removeAttribute("data-insert-token");
        const area=inserted.querySelector(".md-code-area");
        if(area){
          if(inserted.classList.contains("has-diagram")) this.setDiagramEditing(inserted,true);
          area.focus();this.selectOffsets(area,0);
        }
        else this.focusCell(inserted.querySelector("th,td"));
      }
    });
  },
  onKeyDown(event) {
    if(event.isComposing || event.keyCode===229) return;
    // Toolbar inputs/buttons must not inherit a stale selection in code/prose.
    if(event.target.closest?.(".md-code-tools,.md-diagram-preview")) return;
    const completion=this.fenceCompletion;
    if(completion) {
      const items=[...completion.menu.children];
      if(event.key==="ArrowDown"||event.key==="ArrowUp") {
        event.preventDefault();
        completion.active=completion.active<0?(event.key==="ArrowDown"?0:items.length-1):
          (completion.active+(event.key==="ArrowDown"?1:-1)+items.length)%items.length;
        items.forEach((item,i)=>item.setAttribute("aria-selected",String(i===completion.active)));
        items[completion.active].scrollIntoView({block:"nearest"});return;
      }
      if(event.key==="Escape") {event.preventDefault();completion.menu.close();return;}
      if(event.key==="Enter"&&!event.ctrlKey&&!event.altKey&&!event.shiftKey) {
        if(completion.active>=0 || completion.match[3]) {
          event.preventDefault();completion.menu.close();
          this.insertFenceCode(completion.paragraph,completion.match,items[Math.max(0,completion.active)].dataset.value);return;
        }
        completion.menu.close();
      }
    }
    // Keystrokes inside an atom that is in source-edit mode.
    if (this.editingAtom()) {
      const ctrl = event.ctrlKey || event.metaKey;
      if (event.key === "Escape") {
        event.preventDefault(); this.commitAtom(false);
      } else if (ctrl && event.key === "Enter") {
        event.preventDefault(); this.commitAtom(true);
      }
      return;
    }
    // Context: code area or table cell.
    const codeArea = event.target.closest?.(".md-code-area") || this.selectionElement()?.closest(".md-code-area");
    if (codeArea) { this.onCodeKeyDown(event, codeArea); return; }
    const tableCell = event.target.closest?.("th,td") || this.selectionElement()?.closest("th,td");
    if (tableCell && ((event.ctrlKey || event.altKey) && event.key === "Enter" || event.key === "Tab")) {
      this.onTableKeyDown(event, tableCell); return;
    }
    if(event.key==="Enter"&&!event.ctrlKey&&!event.altKey&&!event.shiftKey) {
      // A line ending in a fence plus info string becomes a code block carrying that
      // language (Typora: ``` then Enter inserts a code block). Only the fence is
      // consumed, text before it on the line stays, and a closing run added by
      // auto-pairing is dropped, so no literal fence and no empty block are left.
      const paragraph=this.selectionElement()?.closest("p");
      const text=paragraph?paragraph.textContent:"";
      const match=paragraph&&text.match(/([\s\S]*?)(\x60{3,}|~{3,})([\w+#.-]*)(?:\2)?$/);
      if(match && this.textOffset(paragraph)>=match[1].length){
        event.preventDefault();
        // No explicit info string: apply the configured default language.
        const info=match[3] || (window.__defaultCodeLanguage||"");
        this.insertFenceCode(paragraph,match,info);return;
      }
      // Enter inside a heading: keep the heading for the text before the
      // caret and continue in a normal paragraph. Chromium's default inserts
      // a bare <div>, which block shortcuts (Ctrl+number) and the caret's
      // block lookup do not recognise, so subsequent formatting silently
      // fails on that line.
      const heading=this.selectionElement()?.closest?.("h1,h2,h3,h4,h5,h6");
      if(heading && !heading.closest(".md-code,table,.md-atom,li")){
        event.preventDefault();
        this.splitHeading(heading);
        return;
      }
    }
    // Inline format shortcuts in the continuous surface.
    const ctrl = event.ctrlKey || event.metaKey;
    if (ctrl && !event.shiftKey) {
      const key = event.key.toLowerCase();
      if (key === "b") { event.preventDefault(); this.wrapSelection("**", "**"); return; }
      if (key === "i") { event.preventDefault(); this.wrapSelection("*", "*"); return; }
      if (key === "k") { event.preventDefault(); this.insertLink(); return; }
      // Ctrl+1..6: turn the current block into that heading (0 -> paragraph).
      const num = Number(event.key);
      if ((num >= 1 && num <= 6) || (event.key === "0")) {
        event.preventDefault();
        this.setHeadingLevel(event.key === "0" ? 0 : num);
        return;
      }
    }
    // Backspace at the very start of a structural block: strip its format
    // first (Typora), instead of deleting the line / merging immediately.
    if (event.key === "Backspace" && !ctrl && !event.altKey) {
      if (this.backspaceStripFormat()) { event.preventDefault(); return; }
    }
  },

  // Enter in a heading: the part before the caret keeps its heading, the caret
  // moves into a new normal paragraph after it (empty heading + Enter demotes
  // it in place). Typora semantics, and it keeps subsequent block shortcuts
  // working (a browser-default bare <div> would not be a recognised block).
  splitHeading(host) {
    const doc = document.getElementById("doc");
    doc.focus();
    const offset = this.caretOffsetIn(host);
    const text = host.textContent;
    if (offset === 0) {
      if (text.trim() === "") {
        this._demoteTo(host, "p");
        return;
      }
      const paragraph = document.createElement("p");
      paragraph.innerHTML = "<br>";
      host.before(paragraph);
      this.restoreCaret(paragraph, 0);
    } else {
      const before = text.slice(0, offset), after = text.slice(offset);
      host.innerHTML = MdInline.format(before) || "<br>";
      const paragraph = document.createElement("p");
      paragraph.innerHTML = after ? MdInline.format(after) : "<br>";
      host.after(paragraph);
      this.restoreCaret(paragraph, 0);
    }
    this.postProcess(doc);
    this.scheduleSync();
  },

  // Change one standalone block's tag via the editing framework, which keeps
  // the IME composition anchor and the native undo stack intact (a manual
  // replaceWith detaches the node the input method is composing into).
  // Returns the new element. With selectBlock the whole block is selected
  // first (used while walking a multi-block selection one block at a time).
  formatBlockTag(host, tagName, selectBlock = false) {
    tagName = tagName.toUpperCase();
    // A paragraph/heading inside a quote converts by lifting the whole quote
    // into a standalone block (a plain formatBlock would nest the heading
    // inside the blockquote).
    const quote = host.tagName === "BLOCKQUOTE" ? host
      : (host.parentElement && host.parentElement.tagName === "BLOCKQUOTE"
         ? host.parentElement : null);
    if (quote) {
      const source = host.tagName === "BLOCKQUOTE"
        ? (host.querySelector("p") || host) : host;
      const insertion = document.createElement(tagName);
      insertion.innerHTML = source.innerHTML || "<br>";
      quote.replaceWith(insertion);
      return insertion;
    }
    const selection = getSelection();
    if (selectBlock) {
      const range = document.createRange();
      range.selectNodeContents(host);
      selection.removeAllRanges(); selection.addRange(range);
    }
    document.execCommand("formatBlock", false, tagName);
    const converted = this.selectionElement()?.closest?.(tagName.toLowerCase());
    const result = converted && converted.closest("#doc") ? converted : host;
    if (!result.textContent.trim()) result.innerHTML = "<br>";
    return result;
  },

  // Convert the block the caret is in to a heading of `level` (0 = paragraph).
  setHeadingLevel(level) {
    const doc = document.getElementById("doc");
    doc.focus();
    const target = this.selectionElement();
    // Include bare <div>: leaving a list or exiting a heading via Enter may
    // leave one, and every block command must keep working on it.
    let host = target && target.closest
      ? target.closest("h1,h2,h3,h4,h5,h6,p,li,blockquote,div") : null;
    if (host === doc) host = null; // whole-document selection
    if (host && host.closest(".md-code, table, .md-atom")) return;
    const tagName = level === 0 ? "p" : "h" + level;
    // Any block inside a list item converts the whole item (lists stay valid).
    const item = host && (host.tagName === "LI" ? host : host.closest("li"));
    if (item) {
      this._convertListItem(item, tagName);
      return;
    }
    // A non-collapsed selection spanning several top-level blocks converts
    // each block separately. formatBlock over the cross-block range itself
    // would merge the blocks into one.
    const selection = getSelection();
    if (selection.rangeCount && !selection.isCollapsed) {
      const range = selection.getRangeAt(0);
      const convertible = (el) =>
        /^H[1-6]$|^P$|^DIV$|^BLOCKQUOTE$/.test(el.tagName) && el.closest("#doc");
      const blocks = Array.from(doc.children)
        .filter(el => convertible(el) && range.intersectsNode(el) &&
                      el.textContent.trim() !== "");
      if (blocks.length > 1) {
        const converted = blocks.map(el => this.formatBlockTag(el, tagName, true));
        this.postProcess(doc);
        this.scheduleSync();
        // Collapse into the first converted block so the next keystroke types
        // instead of replacing every selected heading.
        this.restoreCaret(converted[0], 0);
        return;
      }
    }
    if (!host) return;
    const offset = this.caretOffsetIn(host);
    const liftedQuote = host.tagName === "BLOCKQUOTE"
      || (host.parentElement && host.parentElement.tagName === "BLOCKQUOTE");
    const converted = this.formatBlockTag(host, tagName);
    this.postProcess(doc);
    // formatBlock keeps the caret itself for in-place changes; only the
    // blockquote lift needs an explicit restore.
    if (liftedQuote) this.restoreCaret(converted, offset);
    this.scheduleSync();
  },

  // Split the list around one item, replacing only that item with a
  // paragraph/heading while keeping all sibling items and nesting.
  _convertListItem(li, tagName) {
    const list = li.parentElement;
    const items = Array.from(list.children), index = items.indexOf(li);
    const fragment = document.createElement("div");
    const appendList = (subset, offset) => {
      if (!subset.length) return;
      const copy = list.cloneNode(false);
      copy.removeAttribute("data-model-index");
      if (list.tagName === "OL") copy.start = (list.start || 1) + offset;
      subset.forEach(item => copy.appendChild(item.cloneNode(true)));
      fragment.appendChild(copy);
    };
    appendList(items.slice(0, index), 0);
    const middle = document.createElement(tagName);
    // Preserve rich inline content, nested lists and all remaining paragraphs.
    const content = li.cloneNode(true);
    content.querySelector(":scope > input.task-checkbox")?.remove();
    const firstParagraph = content.querySelector(":scope > p");
    if (firstParagraph) {
      middle.innerHTML = firstParagraph.innerHTML || "<br>";
      firstParagraph.remove();
    } else {
      while (content.firstChild && !["UL", "OL", "PRE", "BLOCKQUOTE"].includes(content.firstChild.nodeName)) {
        middle.appendChild(content.firstChild);
      }
      if (!middle.childNodes.length) middle.innerHTML = "<br>";
    }
    const token = "list-edit-" + Math.random().toString(36).slice(2);
    middle.dataset.listEdit = token;
    fragment.appendChild(middle);
    while (content.firstChild) fragment.appendChild(content.firstChild);
    appendList(items.slice(index + 1), index + 1);
    // Chromium normalizes a selected nested list by lifting its replacement
    // out of the parent LI. Replace the complete outer list so the inserted
    // fragment is valid at its insertion point and nesting stays intact.
    let root = list;
    while (root.parentElement.closest("ul,ol")) root = root.parentElement.closest("ul,ol");
    let replacement = fragment.innerHTML;
    if (root !== list) {
      const path = [];
      for (let node = list; node !== root; node = node.parentElement) {
        path.unshift(Array.from(node.parentElement.children).indexOf(node));
      }
      const copy = root.cloneNode(true);
      let nested = copy;
      path.forEach(index => { nested = nested.children[index]; });
      nested.replaceWith(...Array.from(fragment.childNodes));
      replacement = copy.outerHTML;
    }
    document.getElementById("doc").focus();
    const range = document.createRange();
    if (!root.previousElementSibling) {
      // A range beginning in the first list is normalized inside that list
      // by Chromium. An empty leading paragraph gives the native operation
      // a prose boundary outside it; undo restores the original list too.
      const boundary = document.createElement("p");
      boundary.innerHTML = "<br>";
      root.before(boundary);
      range.setStartBefore(boundary); range.setEndAfter(root);
    } else range.selectNode(root);
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
    // Replace at the original range in one native undo transaction.
    document.execCommand("insertHTML", false, replacement);
    const inserted = document.querySelector('[data-list-edit="' + token + '"]');
    if (inserted) {
      inserted.removeAttribute("data-list-edit");
      this.restoreCaret(inserted, tagName === "p" ? 0 : inserted.textContent.length);
    }
    this.postProcess(document.getElementById("doc"));
    this.scheduleSync();
  },

  // Return true (and strip the format) when Backspace is pressed with the caret
  // at the start of a heading/list/quote block.
  backspaceStripFormat() {
    const target = this.selectionElement();
    if (!target || !target.closest) return false;
    const selection = getSelection();
    if (!selection.isCollapsed || selection.anchorOffset !== 0) {
      // caret may be in a child node at its start; check global offset 0.
      if (this.caretOffsetIn(target.closest("#doc")) !== 0) return false;
    }
    const host = target.closest("h1,h2,h3,h4,h5,h6,li,blockquote");
    if (!host || host.closest(".md-code, table, .md-atom")) return false;
    // Must be at the very start of THIS block's text.
    if (this.caretOffsetIn(host) !== 0) return false;
    if (/^H[1-6]$/.test(host.tagName)) {
      document.getElementById("doc").focus();
      this.formatBlockTag(host, "p");
      this.scheduleSync();
      return true;
    }
    if (host.tagName === "LI") {
      this._demoteListItem(host);
      return true;
    }
    if (host.tagName === "BLOCKQUOTE") {
      this._demoteTo(host.querySelector("p") || host, "p", host);
      return true;
    }
    return false;
  },

  _demoteTo(host, tagName, whole) {
    document.getElementById("doc").focus();
    const node = whole || host;
    const p = document.createElement(tagName);
    p.innerHTML = host.innerHTML || "<br>";
    node.replaceWith(p);
    this.restoreCaret(p, 0);
    this.scheduleSync();
  },

  _demoteListItem(li) {
    // Turn only this item into a paragraph; keep sibling items.
    this._convertListItem(li, "p");
  },
};

// QWebChannel ready -> start.
window.addEventListener("DOMContentLoaded", () => {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    App.init(channel.objects.bridge);
  });
});

window.__mdnoteDeliver = function(command) {
  const run=()=>{if(App.surfaceReady){(0,eval)(command);}else setTimeout(run,20);};run();
};
