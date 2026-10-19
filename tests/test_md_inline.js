const assert = require("node:assert/strict");
const { test } = require("node:test");
const MdInline = require("../mdnote/editor/web/md_inline.js");
const f = MdInline.format;

test("plain text and escaping", () => {
  assert.equal(f("普通文本"), "普通文本");
  assert.equal(f("a < b & c > d"), "a &lt; b &amp; c &gt; d");
  assert.equal(f("\\*not italic\\*"), "*not italic*");
});

test("strong, em, strike", () => {
  assert.equal(f("**bold**"), "<strong>bold</strong>");
  assert.equal(f("__bold__"), "<strong>bold</strong>");
  assert.equal(f("*italic*"), "<em>italic</em>");
  assert.equal(f("_italic_"), "<em>italic</em>");
  assert.equal(f("~~strike~~"), "<del>strike</del>");
  assert.equal(f("前 **bold** 后"), "前 <strong>bold</strong> 后");
});

test("inline code is literal and wins over other markup", () => {
  assert.equal(f("`**not bold**`"), "<code>**not bold**</code>");
  assert.equal(f("a `x*y` b"), "a <code>x*y</code> b");
});

test("links and images", () => {
  assert.equal(f("[text](https://a.com)"),
    '<a href="https://a.com">text</a>');
  assert.equal(f("![alt](p.png)"), '<img alt="alt" src="p.png">');
  assert.equal(f("see [docs](https://d.io) now"),
    'see <a href="https://d.io">docs</a> now');
});

test("nested inline markup inside strong/link", () => {
  assert.equal(f("**bold and `code`**"),
    "<strong>bold and <code>code</code></strong>");
  assert.equal(f("[**hi**](https://a.com)"),
    '<a href="https://a.com"><strong>hi</strong></a>');
});

test("unclosed or lone markers stay literal", () => {
  assert.equal(f("a * b * c"), "a * b * c");
  assert.equal(f("2 * 3"), "2 * 3");
  assert.equal(f("**unclosed"), "**unclosed");
});

test("multiple marks in one line", () => {
  assert.equal(f("**a** and *b* and ~~c~~"),
    "<strong>a</strong> and <em>b</em> and <del>c</del>");
});

test("inline math keeps TeX and stays round-trippable", () => {
  const html = f("energy $x^2$ here");
  assert.match(html, /class="math-inline"/);
  assert.match(html, /data-tex="x\^2"/);
  // TeX stays as the span text so typing round-trips.
  assert.match(html, />x\^2</);
});

test("lone dollar signs are not treated as math", () => {
  assert.equal(f("cost $5 and $ 7"), "cost $5 and $ 7");
  assert.equal(f("$ unclosed"), "$ unclosed");
});
