// Continuous (Typora-style) live editor.
//
// The whole document lives in one contenteditable surface (#doc), so the native
// caret/selection can cross headings/paragraphs/lists/quotes/tables: blank lines,
// Ctrl+A and multi-paragraph selection just work. Code has a persistent editor
// with a separate highlight mirror. Complex blocks (Mermaid, math, front matter)
// are atoms with an inline source editor. After any edit the surface is converted
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
    document.addEventListener("keyup", () => this.updateHeadingHint());
    document.addEventListener("beforeinput", (e) => this.onBeforeInput(e));
    document.addEventListener("input", (e) => this.onInput(e));
    document.addEventListener("mousedown", (e) => this.onMouseDown(e), true);
    document.addEventListener("selectionchange", () => this.scheduleHint());
    document.addEventListener("paste",event=>{
      if(this.activeAtom) return;
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
    const el = this.ensureHint();
    const selection = getSelection();
    if (!selection.rangeCount || this.activeAtom) { el.hidden = true; return; }
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
    const codeArea=event.target.closest?.(".md-code-area")||this.selectionElement()?.closest(".md-code-area");
    if(codeArea) {
      if(window.__autoBracket && event.inputType==="insertText" && event.data) {
        const {start,end}=this.offsets(codeArea);
        const edit=CodeEditing.pair(HtmlToMd.codeText(codeArea),start,end,event.data,codeArea.closest(".md-code").dataset.lang);
        if(edit){event.preventDefault();this.applyCodeEdit(codeArea,edit);}
      }
      return;
    }
    if (this.activeAtom || !window.__autoBracket ||
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
    return Promise.resolve(this.bridge.loadSurfaceHtml())
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

  // Set up persistent code editors and render Mermaid atoms.
  postProcess(doc) {
    doc.querySelectorAll(".md-code").forEach(block=>{this.setupCode(block);this.refreshCode(block);});
    this.applyCodePrefs();
    doc.querySelectorAll("table").forEach(table=>table.title="Ctrl+Enter 新增行 · Alt+Enter 新增列 · Tab 下一个单元格");
    // Task checkboxes are enabled for display; toggling is handled once by
    // the capture-phase mousedown delegation (onMouseDown), which survives
    // surface rebuilds without per-element rebinding.
    doc.querySelectorAll("input.task-checkbox").forEach((cb)=>{
      cb.removeAttribute("disabled");
      cb.setAttribute("tabindex", "-1");
    });
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
    this.updateHeadingHint();
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
    if(this.activeAtom) this.activeAtom.dataset.md=this.activeAtom.textContent;
    return HtmlToMd.serialize(document.getElementById("doc"));
  },

  onInput(event) {
    const area=event?.target.closest?.(".md-code-area");
    if(area) this.refreshCode(area.closest(".md-code"));
    if (this.activeAtom) return; // atom edits sync on commit
    this.scheduleSync();
    // Convert immediately (synchronous) so markers never linger.
    this.formatCurrentBlock(event.data);
    this.scheduleHint();
  },

  // Characters that can CLOSE an inline mark; only they trigger an inline
  // re-render (Typora keeps raw markdown visible while you type the inside).
  INLINE_CLOSERS: new Set(["*", "_", "~", "`", ")", "]"]),

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
    const before = host.textContent;
    if (!/[`*_~]|\]\(/.test(before)) return;
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
    const cell=event.target.closest?.("th,td");
    if(cell) this.lastTableCell=cell;
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
    input.spellcheck=false;
    input.autocomplete="off";
    const cur=block.dataset.lang||"";
    input.value=cur;
    input.placeholder="纯文本";
    input.title="输入语言（如 c 联想 C/C++/C#），或点击选择";
    const list=document.createElement("div");
    list.className="md-code-lang-list";
    list.hidden=true;
    langWrap.append(input,list);

    const applyLanguage=(value)=>{
      const normalized=CodeEditing.language(value||"");
      block.dataset.lang=normalized;
      block.querySelector(".md-code-lang").textContent=normalized||"text";
      input.value=normalized;
      this.refreshCode(block); this.pushSurface();
    };
    const renderList=(filter)=>{
      const q=(filter||"").toLowerCase().trim();
      const matches=CodeEditing.languages
        .filter(([value,label])=>!q||value.toLowerCase().includes(q)||label.toLowerCase().includes(q))
        .slice(0,10);
      if(!matches.length){list.hidden=true;list.innerHTML="";return;}
      list.innerHTML="";
      matches.forEach(([value,label])=>{
        const item=document.createElement("button");
        item.type="button";
        item.className="md-code-lang-item";
        item.textContent=label;
        item.dataset.value=value;
        // Mouse selection (mousedown fires before the input loses focus).
        item.addEventListener("mousedown",(e)=>{
          e.preventDefault();
          applyLanguage(value);
          list.hidden=true;
          area.focus();
        });
        list.appendChild(item);
      });
      list.hidden=false;
    };
    input.addEventListener("input",()=>renderList(input.value));
    input.addEventListener("focus",()=>renderList(input.value));
    input.addEventListener("keydown",(e)=>{
      if(e.key==="Enter"){
        e.preventDefault();
        const first=list.querySelector(".md-code-lang-item");
        applyLanguage(first?first.dataset.value:input.value);
        list.hidden=true;
        area.focus();
      }else if(e.key==="Escape"){ list.hidden=true; }
      else if(e.key==="ArrowDown"&&!list.hidden){
        e.preventDefault(); list.querySelector(".md-code-lang-item")?.focus();
      }
    });
    document.addEventListener("mousedown",(e)=>{
      if(!langWrap.contains(e.target)) list.hidden=true;
    });
    input.addEventListener("change",()=>applyLanguage(input.value));

    const hint=document.createElement("span");
    hint.className="md-code-hint";hint.textContent="Tab 缩进 · Ctrl+Enter 退出";
    const copy=document.createElement("button");
    copy.type="button";copy.textContent="复制";copy.title="复制代码正文";
    copy.addEventListener("mousedown",event=>event.preventDefault());
    copy.addEventListener("click",()=>{
      const selection=getSelection(), saved=selection.rangeCount?selection.getRangeAt(0).cloneRange():null;
      area.focus(); this.selectOffsets(area,0,HtmlToMd.codeText(area).length);
      const ok=document.execCommand("copy");
      if(saved){selection.removeAllRanges();selection.addRange(saved);}
      copy.textContent=ok?"已复制":"复制";setTimeout(()=>copy.textContent="复制",1000);
    });
    tools.append(langWrap,hint,copy);
    const numbers=document.createElement("pre");
    numbers.className="md-code-numbers";numbers.setAttribute("aria-hidden","true");
    area.parentElement.prepend(numbers);

  },

  refreshCode(block) {
    if (!block) return;
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
        if(area){area.focus();this.selectOffsets(area,0);}
        else this.focusCell(inserted.querySelector("th,td"));
      }
    });
  },
  onKeyDown(event) {
    if(event.isComposing || event.keyCode===229) return;
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
        const range=document.createRange();
        if(match[1]) {
          const start=this.caretRange(paragraph,match[1].length);
          const tail=this.caretRange(paragraph,text.length);
          range.setStart(start.startContainer,start.startOffset);
          range.setEnd(tail.startContainer,tail.startOffset);
        } else range.selectNode(paragraph);
        const s=getSelection();s.removeAllRanges();s.addRange(range);
        // No explicit info string: apply the configured default language.
        const info=match[3] || (window.__defaultCodeLanguage||"");
        this.insertMarkdown(match[2]+info+"\n\n"+match[2]);return;
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

  // Convert the block the caret is in to a heading of `level` (0 = paragraph).
  setHeadingLevel(level) {
    const target = this.selectionElement();
    const host = target && target.closest
      ? target.closest("h1,h2,h3,h4,h5,h6,p,li,blockquote") : null;
    if (!host || host.closest(".md-code, table, .md-atom")) return;
    const offset = this.caretOffsetIn(host);
    let text = host.textContent;
    // Normalise to plain text first (strip any list/quote/heading wrapper).
    let insertion;
    if (level === 0) {
      insertion = document.createElement("p");
    } else {
      insertion = document.createElement("h" + level);
    }
    insertion.innerHTML = MdInline.format(text) || "<br>";
    // If inside a list/blockquote, replace the whole structural wrapper.
    const wrapper = host.closest("ul,ol") || (host.tagName === "P" && host.parentElement.tagName === "BLOCKQUOTE" ? host.parentElement : host);
    wrapper.replaceWith(insertion);
    this.restoreCaret(insertion, offset);
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
      this._demoteTo(host, "p");
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
    const node = whole || host;
    const p = document.createElement(tagName);
    p.innerHTML = host.innerHTML || "<br>";
    node.replaceWith(p);
    this.restoreCaret(p, 0);
    this.scheduleSync();
  },

  _demoteListItem(li) {
    const list = li.closest("ul,ol");
    const p = document.createElement("p");
    p.innerHTML = li.innerHTML || "<br>";
    list.replaceWith(p);
    this.restoreCaret(p, 0);
    this.scheduleSync();
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
