const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('../mdnote/editor/web/code_editor.js');
const apply=(s,e)=>s.slice(0,e.start)+e.text+s.slice(e.end);
test('C paired braces create an inner line and aligned closing brace',()=>{
  const e=C.newline('int main() {}',12,12,'c',2);
  assert.equal(apply('int main() {}',e),'int main() {\n    \n}');
  assert.equal(e.caret,17);
});
test('C normal line does not accumulate indentation',()=>{
  const s='int main() {\n    run();';
  assert.equal(apply(s,C.newline(s,s.length,s.length,'c',2)),s+'\n    ');
});
test('Python colon and JavaScript brace use different presets',()=>{
  assert.equal(C.newline('if ok:',6,6,'py',2).text,'\n    ');
  assert.equal(C.newline('if (ok) {',9,9,'js',4).text,'\n  ');
});
test('comments and quoted braces do not add an indent level',()=>{
  for(const s of ['// {','/* { */','puts("{");'])
    assert.equal(C.newline(s,s.length,s.length,'c',2).text,'\n');
});
test('newline replaces a selection rather than counting its indentation',()=>{
  const s='    abc';const e=C.newline(s,4,7,'c',2);
  assert.equal(apply(s,e),'    \n    ');
});
test('outdent removes only line indentation when caret is at the end',()=>{
  const s='    return value';const e=C.tab(s,s.length,s.length,'c',2,true);
  assert.equal(apply(s,e),'return value');assert.equal(e.caret,12);
});
test('selected lines indent and outdent without touching their text',()=>{
  const s='a\nb\nc',e=C.tab(s,0,4,'js',2,false);
  const result=apply(s,e);assert.equal(result,'  a\n  b\nc');
  assert.equal(apply(result,C.tab(result,e.caret,e.selectionEnd,'js',2,true)),s);
});
test('pair wraps selected text and skips existing quote',()=>{
  assert.equal(apply('x',C.pair('x',0,1,'(','c')),'(x)');
  assert.deepEqual(C.pair('""',1,1,'"','c'),{skip:2});
});
test('auto pairs leave string and comment contents alone',()=>{
  assert.equal(C.pair('// ',3,3,'(','c'),null);
  assert.equal(C.pair('"abc',4,4,'(','c'),null);
});
test('unknown languages retain the configured tab width',()=>{
  assert.equal(C.unit('custom',3),'   ');
});
test('language suggestions cover development, data, configuration and diagrams',()=>{
  for(const name of ['cpp','csharp','python','tsx','vue','powershell','yaml','toml',
    'mariadb','cassandra','mermaid','plantuml','dot','latex'])
    assert.ok(C.languages.some(([value])=>value===name),name);
  assert.equal(new Set(C.languages.map(([value])=>value)).size,C.languages.length);
  assert.ok(C.languages.length>100);
});
test('language lookup ranks exact names and searches aliases and Chinese labels',()=>{
  assert.equal(C.suggestions('c')[0][0],'c');
  assert.equal(C.suggestions('c++')[0][0],'cpp');
  assert.equal(C.suggestions('tf')[0][0],'hcl');
  assert.ok(C.suggestions('架构').some(([value])=>value==='mermaid'));
  assert.equal(C.language('  Py  '),'python');
  assert.equal(C.language('custom-lexer'),'custom-lexer');
});
