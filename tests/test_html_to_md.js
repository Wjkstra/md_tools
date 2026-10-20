// Function-level tests for the HTML->Markdown serializer using a minimal DOM.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const HtmlToMd = require("../mdnote/editor/web/html_to_md.js");

function textNode(value) {
  return { nodeType: 3, nodeValue: value, childNodes: [], get textContent() { return value; } };
}

// h("p", {class:"x"}, "raw text", childEl, ...)
function h(tag, attrs, ...kids) {
  const childNodes = kids.map((kid) =>
    typeof kid === "string" ? textNode(kid) : kid);
  return {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    childNodes,
    attributes: attrs || {},
    get textContent() { return childNodes.map((c) => c.textContent).join(""); },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? String(this.attributes[name]) : null;
    },
    get style() { return this.attributes.style || {}; },
    // Minimal descendant lookup by ".class" selector for the serializer.
    querySelector(selector) {
      const wanted = selector.startsWith(".") ? selector.slice(1) : null;
      const stack = [...childNodes];
      while (stack.length) {
        const current = stack.shift();
        if (current.nodeType === 1) {
          const classes = String(current.attributes && current.attributes.class || "").split(/\s+/);
          if (wanted && classes.includes(wanted)) return current;
          stack.push(...(current.childNodes || []));
        }
      }
      return null;
    },
  };
}

const root = (...blocks) => h("div", {}, ...blocks);
const md = (node) => HtmlToMd.serialize(node);

test("headings and paragraph inline marks", () => {
  const doc = root(
    h("h1", {}, "标题"),
    h("h2", {}, "副题"),
    h("p", {}, "普通", h("strong", {}, "加粗"), h("em", {}, "斜体"),
      h("code", {}, "x=1"), h("del", {}, "删")),
  );
  assert.equal(md(doc), [
    "# 标题",
    "## 副题",
    "普通**加粗***斜体*`x=1`~~删~~",
  ].join("\n\n"));
});

test("inline code picks a fence that contains its backticks", () => {
  assert.equal(md(root(h("p", {}, h("code", {}, "x=1")))), "`x=1`");
  // Content holding a backtick needs a longer (double-backtick) fence.
  assert.equal(md(root(h("p", {}, h("code", {}, "a`b")))), "``a`b``");
  // Content starting/ending with a backtick needs surrounding spaces.
  assert.equal(md(root(h("p", {}, h("code", {}, "`x`")))), "`` `x` ``");
});

test("links, images and br line breaks", () => {
  const doc = root(h("p", {},
    h("a", { href: "https://a.com" }, "链接"),
    h("img", { src: "p.png", alt: "图" }),
    h("br"),
    "第二行",
  ));
  assert.equal(md(doc), "[链接](https://a.com)![图](p.png)\n第二行");
});

test("unordered, ordered and nested lists", () => {
  const doc = root(
    h("ul", {},
      h("li", {}, "甲"),
      h("li", {}, "乙", h("ul", {}, h("li", {}, "嵌套")))),
    h("ol", {}, h("li", {}, "一"), h("li", {}, "二")),
  );
  assert.equal(md(doc), [
    "- 甲",
    "- 乙",
    "    - 嵌套",
    "",
    "1. 一",
    "2. 二",
  ].join("\n"));
});

test("task list items keep checkbox state", () => {
  const doc = root(h("ul", {},
    h("li", { class: "task-list-item" },
      h("input", { type: "checkbox", class: "task-checkbox" }),
      "未完成"),
    h("li", { class: "task-list-item" },
      h("input", { type: "checkbox", class: "task-checkbox", checked: "" }),
      "完成"),
  ));
  assert.equal(md(doc), "- [ ] 未完成\n- [x] 完成");
});

test("ordered list preserves explicit start", () => {
  const doc = root(h("ol", { start: "5" },
    h("li", {}, "five"), h("li", {}, "six")));
  assert.equal(md(doc), "5. five\n6. six");
});

test("nested list indents by four spaces", () => {
  const doc = root(h("ul", {},
    h("li", {}, "a", h("ul", {}, h("li", {}, "sub")))));
  assert.equal(md(doc), "- a\n    - sub");
});

test("reference and footnote definitions survive via atom data-md", () => {
  const atom = (cls, source) => h("div", { class: "md-atom " + cls, "data-md": source });
  assert.equal(md(root(atom("atom-reference-def", '[ref]: https://x.io "T"'))),
    '[ref]: https://x.io "T"');
  assert.equal(md(root(atom("atom-footnote-def", "[^n]: Footnote body."))),
    "[^n]: Footnote body.");
});

test("blockquote prefixes every line", () => {
  const doc = root(h("blockquote", {},
    h("p", {}, "引用", h("br"), "第二行")));
  assert.equal(md(doc), "> 引用\n> 第二行");
});

test("code block reads inner editor text and re-fences", () => {
  const block = h("div", { class: "md-code" },
    h("div", { class: "md-code-lang" }, "python"),
    h("pre", { class: "md-code-area" },
      h("code", {},
        h("span", {}, "print"),
        h("span", {}, '("代码")'))));
  assert.equal(md(root(block)), '```python\nprint("代码")\n```');
});

test("code block with text label fences without a language", () => {
  const block = h("div", { class: "md-code" },
    h("div", { class: "md-code-lang" }, "text"),
    h("pre", { class: "md-code-area" }, h("code", {}, "plain")));
  assert.equal(md(root(block)), "```\nplain\n```");
});

test("hr", () => {
  assert.equal(md(root(h("hr"))), "---");
});

test("inline math span serializes back to $tex$", () => {
  const doc = root(h("p", {},
    "energy ",
    h("span", { class: "math-inline", "data-tex": "x^2" }, "x^2"),
    " done"));
  assert.equal(md(doc), "energy $x^2$ done");
});

test("escaped literal span restores the backslash", () => {
  const doc = root(h("p", {},
    "literal ",
    h("span", { class: "md-literal", "data-md": "\\*" }, "*"),
    "asterisk",
    h("span", { class: "md-literal", "data-md": "\\*" }, "*")));
  assert.equal(md(doc), "literal \\*asterisk\\*");
});

test("table with alignment", () => {
  const doc = root(h("table", {},
    h("thead", {}, h("tr", {},
      h("th", {}, "列一"),
      h("th", { style: { textAlign: "right" } }, "列二"))),
    h("tbody", {}, h("tr", {},
      h("td", {}, "a"),
      h("td", { style: { textAlign: "right" } }, "b")))));
  assert.equal(md(doc), [
    "| 列一 | 列二 |",
    "| --- | ---: |",
    "| a | b |",
  ].join("\n"));
});

test("empty paragraphs become blank lines", () => {
  const doc = root(
    h("p", {}, "第一段"),
    h("p", {}),
    h("p", {}, "第三段"),
  );
  assert.equal(md(doc), "第一段\n\n\n第三段");
});

test("code keeps leading/trailing blank lines and uses a safe fence", () => {
  const body='\nconst s="'+String.fromCharCode(96).repeat(3)+'";\n';
  const code=h("div", {class:"md-code","data-lang":"c"},
    h("pre",{class:"md-code-area"},body));
  assert.equal(md(root(code)),String.fromCharCode(96).repeat(4)+"c\n"+body+"\n"+String.fromCharCode(96).repeat(4));
});
test("code reads native DIV and BR line breaks without dropping blank lines", () => {
  const code=h("div",{class:"md-code","data-lang":"c"},
    h("pre",{class:"md-code-area"},"first",h("div",{},"second"),h("div",{},h("br"))));
  assert.equal(HtmlToMd.codeText(code.querySelector(".md-code-area")),"first\nsecond\n");
});
test("empty table cells remain empty and literal pipes are escaped", () => {
  const table=h("table",{},h("thead",{},h("tr",{},h("th",{},"A"))),
    h("tbody",{},h("tr",{},h("td",{},h("br"))),h("tr",{},h("td",{},"one | two"))));
  assert.equal(md(root(table)), "| A |\n| --- |\n|   |\n| one \\| two |");
});
