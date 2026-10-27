// HTML -> Markdown reverse serializer for the continuous (Typora-style) surface.
//
// The rendered document lives in one contenteditable element; after the user
// edits it, this walker converts that DOM back to Markdown. Only the HTML shape
// produced by our own renderer needs to be handled. Usable in the browser and in
// Node (function-level tests); entry point is HtmlToMd.serialize(root).
"use strict";

(function (global) {
  function isElement(node) {
    return node && node.nodeType === 1;
  }

  function tagOf(node) {
    return isElement(node) ? node.tagName.toLowerCase() : "";
  }

  function children(node) {
    return Array.from(node.childNodes || []);
  }

  // Only the element children (text/inline ignored where structure is read).
  function elementChildren(node) {
    return children(node).filter(isElement);
  }

  function attr(node, name) {
    if (!isElement(node)) return null;
    const value = node.getAttribute ? node.getAttribute(name) : null;
    return value == null ? null : String(value);
  }

  // ------------------------------------------------ inline -----------------

  // Backslash-escape plain text so it parses back as the SAME plain text.
  // Text nodes are already-decoded literal content; any Markdown-significant
  // punctuation they contain is never real formatting (real formatting arrives
  // as em/strong/code/... elements and is serialized from those elements).
  function escapeText(value) {
    let text = value.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    // A backslash that would act as an escape must itself be escaped. The set
    // matches the engine's escapable characters: "~" is inert here (no
    // strikethrough extension), so a backslash before it stays single and a
    // bare tilde round-trips without a spurious backslash in exports.
    text = text.replace(/\\(?=[\\`*_{}\[\]()#+\-.!|$<>])/g, "\\\\");
    text = text.replace(/\*/g, "\\*");
    text = text.replace(/`/g, "\\`");
    // "_" is inert between word characters (snake_case); escape it only where
    // a delimiter run could open/close emphasis.
    text = text.replace(/_+/g, (run, offset, whole) => {
      const before = whole[offset - 1] || "";
      const after = whole[offset + run.length] || "";
      return /\w/.test(before) && /\w/.test(after)
        ? run : "\\_".repeat(run.length);
    });
    text = text.replace(/\[/g, "\\[").replace(/\]/g, "\\]");
    // A soft-break continuation can look like a new nested list/heading/quote
    // after it receives Markdown indentation. Preserve its text semantics.
    text = text.replace(
      /(^|\n)([ \t]{0,3})([-+]|#{1,6}|>|\d+[.)])(?=[ \t])/g,
      (_, newline, spaces, marker) => newline + spaces +
        (/\d/.test(marker[0]) ? marker.replace(/[.)]$/, "\\$&") : "\\" + marker));
    // A soft-break line that alone looks like a thematic break or a setext
    // underline would otherwise restructure the block on reparse.
    text = text.replace(/(^|\n)([ \t]{0,3})(=+|-+)[ \t]*$/g,
      (_, newline, spaces, run) => newline + spaces + "\\" + run[0] + run.slice(1));
    text = text.replace(/(^|\n)([ \t]{0,3})([-*_])(?:[ \t]*\3){2,}[ \t]*$/g,
      (_, newline, spaces, ch) => newline + spaces + "\\" + ch);
    return text;
  }

  // Wrap a link/image destination in angle brackets when it would not parse
  // bare: whitespace, or unbalanced parentheses (CommonMark allows one level
  // of balanced parens and angle-bracket destinations for everything else).
  function markdownDestination(url) {
    if (url == null || url === "") return "";
    let angle = /\s|<>/.test(url);
    if (!angle) {
      let depth = 0;
      for (const ch of url) {
        if (ch === "(") depth += 1;
        else if (ch === ")") {
          depth -= 1;
          if (depth < 0) { angle = true; break; }
        }
      }
      if (depth !== 0) angle = true;
    }
    if (!angle) return url;
    return "<" + url.replace(/[<>]/g,
      (ch) => "%" + ch.charCodeAt(0).toString(16).toUpperCase()) + ">";
  }

  // Escape image alt text (a plain attribute value, never formatted nodes).
  function imageAlt(value) {
    return value.replace(/\\/g, "\\\\").replace(/\[/g, "\\[").replace(/\]/g, "\\]");
  }

  // Inline elements the sanitizer keeps that have no Markdown shorthand.
  // They are written back as inline HTML so authored markup survives a round
  // trip; only attributes nh3 itself retains are emitted. The block-level
  // nh3 defaults are intentionally excluded (they need block serializers).
  const INLINE_HTML_TAGS = {
    kbd: null, samp: null, var: null, tt: null, u: null, small: null,
    cite: null, dfn: null, acronym: null, abbr: null, q: null,
    time: null, data: null, bdi: null, bdo: null, ruby: null,
    rt: null, rp: null, rtc: null, wbr: null, ins: null,
  };
  // Attribute the surface sanitizer (nh3 defaults) may keep per tag.
  const INLINE_HTML_ATTRS = {
    bdo: ["dir"], q: ["cite"], ins: ["cite", "datetime"],
  };

  function inlineHtmlTag(node, tag) {
    // <wbr> is void; everything else carries (possibly formatted) children.
    if (tag === "wbr") return "<wbr>";
    let attrs = "";
    for (const name of INLINE_HTML_ATTRS[tag] || []) {
      const value = attr(node, name);
      if (value != null) {
        attrs += " " + name + '="' + value.replace(/&/g, "&amp;")
          .replace(/"/g, "&quot;").replace(/</g, "&lt;") + '"';
      }
    }
    return "<" + tag + attrs + ">" + inlineChildren(node) + "</" + tag + ">";
  }

  function inline(node) {
    if (node.nodeType === 3) return escapeText(node.nodeValue);
    if (!isElement(node)) return "";
    const tag = tagOf(node);
    switch (tag) {
      case "strong": case "b":
        return "**" + inlineChildren(node) + "**";
      case "em": case "i":
        return "*" + inlineChildren(node) + "*";
      case "code":
        return inlineCode(node.textContent);
      case "del": case "s":
        return "~~" + inlineChildren(node) + "~~";
      case "a": {
        const href = attr(node, "href");
        return href == null ? inlineChildren(node)
          : "[" + inlineChildren(node) + "]("
            + markdownDestination(href) + linkTitle(node) + ")";
      }
      case "img": {
        // data-md-src preserves the document-relative path even though the
        // live preview rewrites src to a file:// URL.
        const src = attr(node, "data-md-src") || attr(node, "src") || "";
        return "![" + imageAlt(attr(node, "alt") || "") + "]("
          + markdownDestination(src) + linkTitle(node) + ")";
      }
      case "br":
        return "\n";
      case "input": {
        // Task checkbox handled by its parent <li>; nothing to emit inline.
        return "";
      }
      // Inline HTML the sanitizer keeps on purpose: write the tags back so
      // authored inline markup survives a round trip.
      case "mark":
        return "<mark>" + inlineChildren(node) + "</mark>";
      case "sup":
        return "<sup>" + inlineChildren(node) + "</sup>";
      case "sub":
        return "<sub>" + inlineChildren(node) + "</sub>";
      case "span": {
        const cls = attr(node, "class") || "";
        // Inline math keeps its TeX in data-tex; emit $tex$.
        if (cls.indexOf("math-inline") >= 0) {
          const tex = attr(node, "data-tex") != null
            ? attr(node, "data-tex") : node.textContent;
          return "$" + tex + "$";
        }
        // Escaped literal (e.g. \*) restored verbatim from data-md.
        if (cls.indexOf("md-literal") >= 0 && attr(node, "data-md") != null) {
          return attr(node, "data-md");
        }
        return inlineChildren(node);
      }
      case "p": case "div":
        return inlineChildren(node);
      default:
        if (Object.prototype.hasOwnProperty.call(INLINE_HTML_TAGS, tag)) {
          return inlineHtmlTag(node, tag);
        }
        return inlineChildren(node);
    }
  }

  function linkTitle(node) {
    const title = attr(node, "title");
    return title == null ? "" : ' "' + title.replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;").replace(/</g, "&lt;") + '"';
  }

  function inlineChildren(node) {
    const nodes = children(node);
    return nodes.map((child, i) => inlineAfter(child, nodes[i - 1])).join("");
  }

  function inlineAfter(node, previous) {
    const text = inline(node);
    // <br />\n contains one visible break. Do not mutate the live text node
    // while serializing; doing so also breaks the browser's undo history.
    return node.nodeType === 3 && tagOf(previous) === "br" ? text.replace(/^\n/, "") : text;
  }

  // Serialize inline code with a fence long enough to contain any
  // backticks in the content (CommonMark): ``a`b`` for content with one.
  function inlineCode(text) {
    let longest = 0, m;
    const re = /`+/g;
    while ((m = re.exec(text)) !== null) {
      if (m[0].length > longest) longest = m[0].length;
    }
    // Empty code needs double backticks with one space inside ("`` ``");
    // a single empty pair would parse as two literal backticks on reparse.
    if (text === "") return "`` ``";
    const fence = '`'.repeat(longest + 1);
    const pad = /^`|`$/.test(text) ? ' ' : '';
    return fence + pad + text + pad + fence;
  }

  // A blank structural line: empty or just a <br>.
  function isBlankInlineText(text) {
    return text.replace(/ /g, " ").trim() === "";
  }

  // ------------------------------------------------ lists ------------------

  function isTaskItem(li) {
    const first = elementChildren(li)[0];
    return first && first.tagName.toLowerCase() === "input"
      && (attr(first, "type") || "").toLowerCase() === "checkbox"
      && (attr(first, "class") || "").indexOf("task-checkbox") >= 0;
  }

  function taskChecked(li) {
    const first = elementChildren(li)[0];
    return attr(first, "checked") != null;
  }

  function renderList(list, markerPrefix) {
    const ordered = tagOf(list) === "ol";
    // Preserve an explicit start number (e.g. <ol start="5">).
    const startAttr = ordered ? parseInt(attr(list, "start"), 10) : NaN;
    const start = ordered && Number.isFinite(startAttr) && startAttr >= 1
      ? startAttr : 1;
    const items = [];
    const loose = elementChildren(list).some(li => elementChildren(li).some(c => tagOf(c) === "p"));
    const BLOCK_TAGS = ["p", "div", "ul", "ol", "pre", "blockquote",
      "h1", "h2", "h3", "h4", "h5", "h6", "table"];
    elementChildren(list).forEach(function (li, index) {
      if (tagOf(li) !== "li") return;
      const marker = isTaskItem(li) ? "- [" + (taskChecked(li) ? "x" : " ") + "] "
        : ordered ? (start + index) + ". " : "- ";
      // Each part carries its own lines plus whether continuation lines need
      // list indentation: block children do, lazy prose continuations do not
      // (indenting them changes how Python-Markdown parses the item).
      const parts = [];
      let pending = "";
      let hasBlock = false;
      const nodes = children(li);
      const flushInline = () => {
        if (pending.trim()) {
          parts.push({ lines: pending.trim().split("\n"), indent: hasBlock, sep: "\n\n" });
        }
        pending = "";
      };
      nodes.forEach((child, i) => {
        const tag = tagOf(child);
        if (BLOCK_TAGS.includes(tag)) {
          flushInline();
          hasBlock = true;
          const nested = tag === "ul" || tag === "ol";
          parts.push({
            lines: block(child).split("\n"),
            indent: true,
            sep: nested && !loose ? "\n" : "\n\n",
          });
        } else pending += inlineAfter(child, nodes[i - 1]);
      });
      flushInline();
      const out = [];
      parts.forEach((part, partIndex) => {
        if (partIndex > 0 && part.sep === "\n\n") out.push("");
        part.lines.forEach((line, lineIndex) => {
          const itemFirstLine = partIndex === 0 && lineIndex === 0 && out.length === 0;
          if (itemFirstLine) {
            out.push(line); // glued to the marker
          } else {
            out.push(part.indent && line ? "    " + line : line);
          }
        });
      });
      const first = out.shift() || "";
      items.push(marker + first + out.map(line => "\n" + line).join(""));
    });
    return items.join(loose ? "\n\n" : "\n").split("\n");
  }

  // ------------------------------------------------ code -------------------

  // Native paste/Enter may produce DIV/BR nodes; textContent drops their breaks.
  function codeText(area) {
    function read(parent) {
      const children=Array.from(parent.childNodes||[]);
      return children.map((child,i)=>{
        if(child.nodeType===3) return child.nodeValue;
        const tag=tagOf(child);
        if(tag==="br") return i===children.length-1 ? "" : "\n";
        const text=read(child);
        return (["div","p"].includes(tag)&&i>0?"\n":"")+text;
      }).join("");
    }
    return read(area);
  }

  function renderCode(pre) {
    // Pygments wraps source in <pre><code> with highlight spans; take plain text.
    const code = elementChildren(pre).find(function (child) {
      return tagOf(child) === "code";
    });
    // These <pre> blocks are rendered indented code (fenced code uses the
    // persistent .md-code editor). Serialize them as indented code too: that
    // keeps embedded fence lines literal and survives list/quote nesting
    // (list indentation adds the remaining columns on continuation lines).
    const body = (code || pre).textContent.replace(/\n$/, "");
    return body.split("\n").map(function (line) {
      return line.length ? "    " + line : "";
    }).join("\n");
  }

  // ------------------------------------------------ blockquote -------------

  function renderBlockquote(quote) {
    const inner = elementChildren(quote).map(block).join("\n\n");
    return inner.split("\n").map(function (line) {
      return line === "" ? ">" : "> " + line;
    }).join("\n");
  }

  // ------------------------------------------------ table ------------------

  function cellAlign(cell) {
    const fromStyle = (cell.getAttribute && cell.style && cell.style.textAlign) || "";
    const fromAttr = attr(cell, "align") || "";
    return (fromStyle || fromAttr || "").toLowerCase();
  }

  function cellText(cell) {
    // Only add a table escape when the pipe is not already escaped. Escapes
    // carried by md-literal spans have already been serialized once.
    const text = inlineChildren(cell).trim().replace(/(\\*)\|/g,
      (match, slashes) => slashes + (slashes.length % 2 ? "" : "\\") + "|").replace(/\n/g, "<br>");
    return text === "" ? " " : text;
  }

  function renderTable(table) {
    const thead = elementChildren(table).find(function (child) {
      return tagOf(child) === "thead";
    });
    const tbody = elementChildren(table).find(function (child) {
      return tagOf(child) === "tbody";
    });

    function headCells() {
      if (thead) {
        const row = elementChildren(thead).find(function (c) { return tagOf(c) === "tr"; });
        return row ? elementChildren(row).filter(function (c) { return tagOf(c) === "th"; }) : [];
      }
      // Table without thead: first row doubles as header.
      const firstRow = elementChildren(table).find(function (c) { return tagOf(c) === "tr"; });
      return firstRow ? elementChildren(firstRow).filter(function (c) {
        return tagOf(c) === "th" || tagOf(c) === "td";
      }) : [];
    }

    function bodyRows() {
      const rowsParent = tbody || table;
      return elementChildren(rowsParent).filter(function (c) { return tagOf(c) === "tr"; })
        .filter(function (row) {
          return thead || tbody || elementChildren(table)[0] !== row;
        });
    }

    const headers = headCells();
    const lines = [];
    lines.push("| " + headers.map(cellText).join(" | ") + " |");
    lines.push("| " + headers.map(function (cell) {
      const align = cellAlign(cell);
      return align === "center" ? ":---:" : align === "right" ? "---:"
        : align === "left" ? ":---" : "---";
    }).join(" | ") + " |");
    bodyRows().forEach(function (row) {
      const cells = elementChildren(row).filter(function (c) {
        return tagOf(c) === "td" || tagOf(c) === "th";
      });
      lines.push("| " + cells.map(cellText).join(" | ") + " |");
    });
    return lines.join("\n");
  }

  // ------------------------------------------------ blocks -----------------

  function block(node) {
    if (isElement(node)) {
      const cls = (attr(node, "class") || "").split(/\s+/);
      if (cls.includes("md-atom")) {
        // Complex block atom: restore its verbatim original Markdown.
        return attr(node, "data-md") != null ? attr(node, "data-md") : "";
      }
      if (cls.includes("md-code")) {
        // Always-editable code block: read the inner editor text and re-fence.
        const area = node.querySelector(".md-code-area");
        const label = (node.querySelector(".md-code-lang") || {}).textContent || "";
        const lang = attr(node,"data-lang") ?? (label.trim() === "text" ? "" : label.trim());
        const body = codeText(area);
        // Preserve original fence style/info and unfinished blocks until edited.
        if(attr(node,"data-source")===body && attr(node,"data-original-lang")===lang &&
           attr(node,"data-md") != null) return attr(node,"data-md");
        const runs = body.match(/\x60+/g) || [];
        const fence = "\x60".repeat(runs.reduce((longest,run)=>Math.max(longest,run.length+1),3));
        return fence + lang + "\n" + body + "\n" + fence;
      }
    }
    const tag = tagOf(node);
    switch (tag) {
      case "h1": case "h2": case "h3":
      case "h4": case "h5": case "h6": {
        const level = Number(tag[1]);
        let text = inlineChildren(node);
        // Authored attr_list ("# Title {#id .cls k=v}"), carried verbatim
        // in data-md-attrs; data-md-attr-id is the older id-only fallback.
        const authoredAttrs = attr(node, "data-md-attrs");
        const authoredId = attr(node, "data-md-attr-id");
        if (authoredAttrs) text += " {" + authoredAttrs + "}";
        else if (authoredId) text += " {#" + authoredId + "}";
        return "#".repeat(level) + " " + text;
      }
      case "p": {
        const text = inlineChildren(node);
        return isBlankInlineText(text) ? "" : text;
      }
      case "ul": case "ol":
        return renderList(node).join("\n");
      case "blockquote":
        return renderBlockquote(node);
      case "pre":
        return renderCode(node);
      case "hr":
        return "---";
      case "table":
        return renderTable(node);
      default:
        // Unknown wrapper (e.g. .codehilite div holding a <pre>): pass through.
        const pre = elementChildren(node).find(function (child) {
          return tagOf(child) === "pre";
        });
        if (pre) return renderCode(pre);
        return inlineChildren(node);
    }
  }

  function serialize(root) {
    const raw = elementChildren(root).map(block);
    // Trim leading/trailing blank blocks (blank lines there are meaningless).
    let first = 0;
    while (first < raw.length && raw[first] === "") first += 1;
    let last = raw.length;
    while (last > first && raw[last - 1] === "") last -= 1;
    const parts = raw.slice(first, last);

    // Join non-blank blocks with a standard paragraph break (2 newlines);
    // each interior blank block is one extra blank line (1 more newline).
    const output = [];
    let pendingBlanks = 0;
    parts.forEach(function (text) {
      if (text === "") {
        pendingBlanks += 1;
        return;
      }
      if (output.length) {
        output.push("\n".repeat(2 + pendingBlanks));
      }
      output.push(text);
      pendingBlanks = 0;
    });
    return output.join("");
  }

  const api = { serialize: serialize, codeText: codeText, block: block, inline: inline };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  global.HtmlToMd = api;
})(typeof window !== "undefined" ? window : globalThis);
