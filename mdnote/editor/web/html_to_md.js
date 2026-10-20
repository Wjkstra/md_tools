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

  function inline(node) {
    if (node.nodeType === 3) return node.nodeValue; // text: already entity-decoded
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
          : "[" + inlineChildren(node) + "](" + href + ")";
      }
      case "img": {
        // data-md-src preserves the document-relative path even though the
        // live preview rewrites src to a file:// URL.
        const src = attr(node, "data-md-src") || attr(node, "src") || "";
        const alt = attr(node, "alt") || "";
        return "![" + alt + "](" + src + ")";
      }
      case "br":
        return "\n";
      case "input": {
        // Task checkbox handled by its parent <li>; nothing to emit inline.
        return "";
      }
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
        return inlineChildren(node);
    }
  }

  function inlineChildren(node) {
    const nodes = children(node);
    let out = "";
    nodes.forEach(function (child, i) {
      let piece = inline(child);
      // The Markdown engine emits "<br />\n" where the newline is only source
      // formatting (the <br> already is the break). Drop that one newline so a
      // soft line break is not serialized as two.
      if (tagOf(child) === "br" && i + 1 < nodes.length) {
        const next = nodes[i + 1];
        if (next.nodeType === 3 && next.nodeValue.charAt(0) === "\n") {
          next.nodeValue = next.nodeValue.replace(/^\n/, "");
        }
      }
      out += piece;
    });
    return out;
  }

  // Serialize inline code with a fence long enough to contain any
  // backticks in the content (CommonMark): ``a`b`` for content with one.
  function inlineCode(text) {
    let longest = 0, m;
    const re = /`+/g;
    while ((m = re.exec(text)) !== null) {
      if (m[0].length > longest) longest = m[0].length;
    }
    const fence = '`'.repeat(longest + 1);
    const pad = /^`|`$/.test(text) ? ' ' : '';
    return fence + pad + text + pad + fence;
  }

  // A blank structural line: empty or just a <br>.
  function isBlankInlineText(text) {
    return text.replace(/ /g, " ").trim() === "";
  }

  // ------------------------------------------------ lists ------------------

  function listItemInline(li) {
    // Inline content excludes nested lists (handled separately).
    const parts = children(li)
      .filter(function (child) {
        if (!isElement(child)) return true;
        return child.tagName.toLowerCase() !== "ul"
          && child.tagName.toLowerCase() !== "ol";
      })
      .map(inline);
    return parts.join("").replace(/\s+$/, "");
  }

  function nestedList(li) {
    return elementChildren(li).find(function (child) {
      const t = child.tagName.toLowerCase();
      return t === "ul" || t === "ol";
    }) || null;
  }

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
    const lines = [];
    elementChildren(list).forEach(function (li, index) {
      if (tagOf(li) !== "li") return;
      let head;
      if (isTaskItem(li)) {
        head = "- [" + (taskChecked(li) ? "x" : " ") + "] " + listItemInline(li);
      } else if (ordered) {
        head = (start + index) + ". " + listItemInline(li);
      } else {
        head = "- " + listItemInline(li);
      }
      lines.push(head);
      const nested = nestedList(li);
      if (nested) {
        renderList(nested).forEach(function (line) {
          // Python-Markdown requires 4 spaces to keep nested list hierarchy.
          lines.push(line.replace(/^/gm, "    "));
        });
      }
    });
    return lines;
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
    const body = (code || pre).textContent.replace(/\n$/, "");
    const lang = attr(pre, "data-lang") || attr(code, "data-lang") || "";
    const fence = "```";
    return fence + lang + "\n" + body + "\n" + fence;
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
    const text = inlineChildren(cell).trim().replace(/\|/g, "\\|").replace(/\n/g, "<br>");
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
        return "#".repeat(level) + " " + inlineChildren(node);
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
