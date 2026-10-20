// Inline Markdown -> HTML for the live (Typora-style) surface.
//
// Pure, dependency-free and usable in both the browser and Node tests. It turns
// a single line of typed Markdown into HTML for inline features that must
// re-render instantly without a round trip to Python: code, images, links,
// strong/emphasis and strike. Backslash escapes are respected.
"use strict";

(function (global) {
  function escapeHtml(text) {
    return String(text).replace(/[&<>"]/g, (ch) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]
    ));
  }

  // Each rule: opening token match -> { length consumed, html produced }.
  // Order matters; at each position the earliest/most specific wins.
  function makeRules() {
    return [
      {
        // Inline code: content is literal, never re-parsed.
        re: /`+([^`]+?)`+/,
        render: (m) => `<code>${escapeHtml(m[1])}</code>`,
      },
      {
        re: /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/,
        render: (m) => `<img alt="${escapeHtml(m[1])}" src="${escapeHtml(m[2])}">`,
        literal: true,
      },
      {
        re: /\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/,
        render: (m) => `<a href="${escapeHtml(m[2])}">${format(m[1])}</a>`,
      },
      {
        // Inline math: $expr$. The span keeps the literal TeX as its text so
        // typing round-trips; postProcess paints it with KaTeX visually.
        re: /(?<![\\$])\$([^\s$][^$]*?[^\s$]|[^\s$])\$(?!\w)/,
        render: (m) => {
          const tex = m[1];
          return `<span class="math-inline" data-tex="${escapeHtml(tex)}">${escapeHtml(tex)}</span>`;
        },
      },
      {
        // Strong: the character next to each delimiter must not be whitespace.
        re: /\*\*([^\s*][\s\S]*?[^\s*]|[^\s*])\*\*/,
        render: (m) => `<strong>${format(m[1])}</strong>`,
      },
      {
        re: /__([^\s_][\s\S]*?[^\s_]|[^\s_])__/,
        render: (m) => `<strong>${format(m[1])}</strong>`,
      },
      {
        re: /(?<![\w*])\*([^\s*][^*]*?[^\s*]|[^\s*])\*(?!\w)/,
        render: (m) => `<em>${format(m[1])}</em>`,
      },
      {
        re: /(?<![\w_])_([^\s_][^_]*?[^\s_]|[^\s_])_(?!\w)/,
        render: (m) => `<em>${format(m[1])}</em>`,
      },
      {
        re: /~~([\s\S]+?)~~/,
        render: (m) => `<del>${format(m[1])}</del>`,
      },
    ];
  }

  let RULES = makeRules();

  function format(text) {
    let out = "";
    let i = 0;
    while (i < text.length) {
      const ch = text[i];
      if (ch === "\\") {
        const next = text[i + 1];
        if (next && "`*_~[]()!#<>\\".includes(next)) {
          // Preserve the escape so saving restores "\X" instead of turning a
          // literal asterisk into emphasis. Visual shows the bare character.
          out += `<span class="md-literal" data-md="\\${escapeHtml(next)}">`
            + escapeHtml(next) + "</span>";
          i += 2; continue;
        }
        out += escapeHtml("\\"); i += 1; continue;
      }
      const rest = text.slice(i);
      let chosen = null;
      for (const rule of RULES) {
        const m = rule.re.exec(rest);
        if (m && (chosen === null || m.index < chosen.index)) {
          chosen = { rule, m, index: m.index };
        }
      }
      if (chosen && chosen.index === 0) {
        out += chosen.rule.render(chosen.m);
        i += chosen.m[0].length;
        continue;
      }
      // Earliest future match: emit literal text up to it and loop.
      if (chosen) {
        const segment = text.slice(i, i + chosen.index);
        // Do not leap over a backslash escape in the skipped segment: stop
        // on the backslash so the escape branch above handles the next char.
        const slash = segment.indexOf("\\");
        if (slash >= 0) {
          out += escapeHtml(text.slice(i, i + slash));
          i += slash;
          continue;
        }
        out += escapeHtml(segment);
        i += chosen.index;
        continue;
      }
      out += escapeHtml(ch);
      i += 1;
    }
    return out;
  }

  const api = { format, formatLine: format, escapeHtml };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.MdInline = api;
})(typeof window !== "undefined" ? window : globalThis);
