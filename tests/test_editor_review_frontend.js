// Function-level regressions use the shipped controller without a browser engine.
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assert = require("node:assert/strict");
const {test} = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../mdnote/editor/web/app.js"), "utf8");
function controller(document = {}) {
  const context = {document, window:{addEventListener(){}}, Node:{TEXT_NODE:3, ELEMENT_NODE:1},
    getSelection:()=>({rangeCount:0})};
  vm.runInNewContext(source + ";globalThis.testApp=App", context);
  return {app:context.testApp, context};
}
function textNode(text) { return {nodeType:3, nodeValue:text}; }
function anchor(text, href) {
  return {nodeType:1, tagName:"A", childNodes:[textNode(text)],
    getAttribute(name){return name === "href" ? href : null;}};
}
function tableFixture(raw) {
  const texts = ["Header", "Link", "bold", "website"];
  const cells = texts.map(textContent => ({
    textContent, childNodes:[textNode(textContent)], dataset:{}, style:{textAlign:""}, contentEditable:"false", handlers:{},
    setAttribute(){}, getAttribute(){return null;},
    addEventListener(name, fn){this.handlers[name]=fn;}, closest(){return this;},
    get isContentEditable(){return this.contentEditable === "true";},
  }));
  const rows = [0, 2].map(start => ({querySelectorAll(){return cells.slice(start, start+2);}}));
  const table = {isConnected:true, querySelectorAll(selector){return selector === "tr" ? rows : cells;}};
  const {app} = controller(); app.blocks=[{index:0, raw}];
  const writes=[];
  app.runBridge=(method, args, cb)=>{
    writes.push(args[1]); app.blocks=[{index:0, raw:args[1]}]; cb(app.blocks);
  };
  app.editCell=cell=>cell.contentEditable="true";
  app.attachTableEditor({querySelector(){return table;}}, 0, cells[0]);
  return {app, table, cells, writes};
}
const formatted = "| **Header** | Link |\n| --- | --- |\n| **bold** | [website](https://example.com) |";

test("focusing and blurring a formatted table does not submit", () => {
  const {cells, writes} = tableFixture(formatted);
  cells[0].handlers.blur(); assert.equal(writes.length, 0);
});
test("editing a cell preserves untouched inline Markdown and does not duplicate blur writes", () => {
  const {cells, writes} = tableFixture(formatted);
  cells[0].textContent="Updated"; cells[0].handlers.input();
  assert.equal(writes.length, 1);
  assert.match(writes[0], /\| \*\*bold\*\* \| \[website\]\(https:\/\/example\.com\) \|/);
  cells[0].handlers.blur(); assert.equal(writes.length, 1);
});
test("table source parsing keeps escaped pipes and code spans in their cells", () => {
  const {app} = controller();
  assert.deepEqual(Array.from(app.splitTableRow("| a\\|b | `x|y` | last |")), ["a\\|b", "`x|y`", "last"]);
  assert.deepEqual(Array.from(app.splitTableRow("first | second\\|")), ["first", "second\\|"]);
});
test("edited cell serialization keeps links, emphasis, code, images and line breaks", () => {
  const {app} = controller();
  const cell = {childNodes: [
    textNode("plain "),
    {nodeType:1, tagName:"STRONG", childNodes:[
      {nodeType:1, tagName:"A", childNodes:[textNode("site")],
       getAttribute:n=>n==="href" ? "https://x.io" : null},
    ]},
    textNode(" "),
    {nodeType:1, tagName:"CODE", childNodes:[textNode("a|b")]},
    textNode(" "),
    {nodeType:1, tagName:"IMG", childNodes:[],
     getAttribute:n=>({src:"p.png", alt:"pic"}[n] || null)},
  ]};
  assert.equal(app.cellToMarkdown(cell),
    'plain **[site](https://x.io)** `a\\|b` ![pic](p.png)');
  const multiline = {childNodes: [
    {nodeType:1, tagName:"DIV", childNodes:[textNode("first")]},
    {nodeType:1, tagName:"DIV", childNodes:[textNode("second")]},
  ]};
  assert.equal(app.cellToMarkdown(multiline), "first<br>second");
});
test("editing a link cell keeps the link target instead of flattening to text", () => {
  const raw = "| a |\n| --- |\n| [site](https://example.com) |";
  const {cells, writes} = tableFixture(raw);
  const linkCell = cells[1];
  linkCell.childNodes = [anchor("updated text", "https://example.com")];
  linkCell.textContent = "updated text";
  linkCell.handlers.input();
  assert.equal(writes.length, 1);
  assert.match(writes[0], /\[updated text\]\(https:\/\/example\.com\)/);
});
test("second checkbox keeps its item index when the click is queued", () => {
  const {app} = controller();
  const first={}, second={matches:s=>s === "input.task-checkbox"};
  const block={dataset:{index:"3"},querySelectorAll(){return [first,second];}};
  second.closest=()=>block; app.blocks=Array(5); app.pendingTransform=true;
  let result;
  app.switchTo=(index, options)=>result={index,options};
  app.onMouseDown({button:0,target:second,preventDefault(){},clientX:1,clientY:2});
  app.pendingTransform=false; app.pendingInput.shift()();
  assert.equal(result.index,3); assert.equal(result.options.taskIndex,1); assert.equal(result.options.task,true);
});
function searchDocument() {
  return {
    querySelector(){return null;},
    createElement(){return {
      innerHTML:"", get textContent(){return this.innerHTML.replace(/<[^>]*>/g, "");},
      querySelectorAll(){const m=this.innerHTML.match(/<h\d id="([^"]+)"/);return m?[{id:m[1]}]:[];},
    };},
  };
}
test("whole-model search counts matches outside the mounted range and cycles", () => {
  const {app} = controller(searchDocument());
  app.blocks=Array.from({length:500}, (_,index)=>({index,raw:"paragraph",html:"<p>paragraph</p>"}));
  app.blocks[499]={index:499,raw:"**target** target",html:"<p><strong>target</strong> target</p>"};
  let shown=-1; app.showRenderedBlock=index=>shown=index;
  assert.equal(app.findDocument("target",true).total,2); assert.equal(shown,499);
  assert.equal(app.findDocument("target",true).active,2);
  assert.equal(app.findDocument("target",true).active,1);
});
test("pending find reveals the new block index after a queued split", () => {
  const {app} = controller(searchDocument()); app.pendingTransform=true;
  app.blocks=[{index:0,raw:"target",html:"<p>target</p>"}];
  let shown=-1; app.showRenderedBlock=index=>shown=index;
  assert.equal(app.findDocument("target",true).found,true);
  app.blocks=[{index:0,raw:"new",html:"<p>new</p>"},{index:1,raw:"target",html:"<p>target</p>"}];
  app.pendingTransform=false; app.pendingInput.shift()(); assert.equal(shown,1);
});
test("directory navigation finds an unmounted heading from the model", () => {
  const {app} = controller(searchDocument());
  app.blocks=[{index:450,type:"heading",html:'<h1 id="far-target">far</h1>'}];
  let shown=-1; app.showRenderedBlock=index=>shown=index;
  app.jumpToId("far-target"); assert.equal(shown,450);
});
test("Mermaid preference uses code fence language even without Pygments language classes", () => {
  const {app,context} = controller({createElement(){return {className:"",textContent:""};}});
  app.blocks=[{index:0,type:"code",raw:"```mermaid\ngraph TD; A-->B\n```"}];
  let renders=0, gutters=0;
  context.window.mermaid={initialize(){},run(){renders++;}};
  app.applyCodeLineNumbers=()=>gutters++;
  const el={dataset:{index:"0"},classList:{contains(){return false;}},replaceChildren(){}};
  context.window.__mermaid=false; app.postProcessBlock(el);
  assert.equal(renders,0); assert.equal(gutters,1);
  delete el.dataset.renderPrefs; context.window.__mermaid=true; app.postProcessBlock(el);
  assert.equal(renders,1);
});

test("find keeps Unicode offsets and treats punctuation literally", () => {
  const {app} = controller(searchDocument());
  app.blocks=[{index:0,raw:"İabc target .+ [x]",html:"<p>İabc target .+ [x]</p>"}];
  assert.equal(app.collectDocumentMatches("target").matches[0].start,5);
  assert.equal(app.collectDocumentMatches(".+ [x]").matches.length,1);
});
test("find cycle survives rendering a previously counted draft", () => {
  const doc=searchDocument(), edit={textContent:"changed first"};
  const original=doc.querySelector;
  doc.querySelector=selector=>selector === ".is-editing" ? edit : original(selector);
  const {app} = controller(doc); app.editingIndex=0; app.selectionOffsets=()=>[0,0];
  app.blocks=[{index:0,raw:"first",html:"<p>first</p>"},{index:1,raw:"target target",html:"<p>target target</p>"}];
  app.showRenderedBlock=()=>{};
  assert.equal(app.findDocument("target",true).active,1);
  app.editingIndex=-1; app.blocks[0]={index:0,raw:"changed first",html:"<p>changed first\n</p>"};
  assert.equal(app.findDocument("target",true).active,2);
});
test("code gutters reflect line counts and can be removed", () => {
  let gutters=[];
  const pre={classList:{toggle(){}},querySelectorAll(){return gutters;},
    querySelector(){return {textContent:"first\nsecond\n"};},prepend(g){gutters=[g];}};
  const {app,context}=controller({createElement(){return {setAttribute(){},remove(){gutters=[];}};}});
  const el={querySelectorAll(){return [pre];}};
  context.window.__codeLineNumbers=true; app.applyCodeLineNumbers(el);
  assert.equal(gutters[0].textContent,"1\n2");
  context.window.__codeLineNumbers=false; app.applyCodeLineNumbers(el); assert.equal(gutters.length,0);
});
