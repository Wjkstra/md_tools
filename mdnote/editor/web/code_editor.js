/* Offline language-aware text edits. DOM changes stay in Chromium's undo stack. */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.CodeEditing = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  // Stable Markdown fence names. Other/custom lexer names remain valid input.
  // Diagram presets describe source-only formats explicitly; Mermaid renders offline.
  const languages = [['', '纯文本'],
    ['actionscript','ActionScript'], ['ada','Ada'], ['apacheconf','Apache'],
    ['applescript','AppleScript'], ['arduino','Arduino'], ['asm','Assembly'],
    ['awk','AWK'], ['bash','Bash / Shell'], ['bat','Batch / CMD'], ['bibtex','BibTeX'], ['bicep','Bicep'],
    ['c','C'], ['csharp','C#'], ['cpp','C++'], ['cassandra','Cassandra CQL'],
    ['ceylon','Ceylon'], ['clojure','Clojure'], ['cmake','CMake'], ['cobol','COBOL'],
    ['coffee-script','CoffeeScript'], ['common-lisp','Common Lisp'], ['coq','Coq'],
    ['css','CSS'], ['cuda','CUDA'], ['cypher','Cypher / Neo4j'],
    ['d','D'], ['d2','D2 · 图表源码'], ['dart','Dart'], ['diff','Diff / Patch'],
    ['django','Django / Jinja'], ['docker','Dockerfile'], ['dosini','INI'],
    ['elixir','Elixir'], ['elm','Elm'], ['erlang','Erlang'], ['fsharp','F#'],
    ['fish','Fish Shell'], ['fortran','Fortran'], ['gherkin','Gherkin'], ['glsl','GLSL'], ['go','Go'],
    ['graphql','GraphQL'], ['groovy','Groovy'], ['haskell','Haskell'],
    ['haxe','Haxe'], ['hcl','HCL / Terraform'], ['html','HTML'], ['http','HTTP'],
    ['java','Java'], ['javascript','JavaScript'], ['json','JSON'], ['json5','JSON5'], ['jsonc','JSON with Comments'],
    ['jsx','JSX / React'], ['julia','Julia'], ['kotlin','Kotlin'], ['latex','LaTeX / TeX'],
    ['less','Less'], ['llvm','LLVM'], ['log','Log / 日志'], ['lua','Lua'], ['makefile','Makefile'],
    ['mariadb','MariaDB'], ['markdown','Markdown'], ['math','Math · 公式源码'],
    ['mathematica','Mathematica / Wolfram'], ['matlab','MATLAB'],
    ['mermaid','Mermaid · 流程图 / UML / 架构图'], ['meson','Meson'],
    ['mongodb','MongoDB'], ['mysql','MySQL'], ['nasm','NASM'], ['nginx','Nginx'], ['nim','Nim'],
    ['nix','Nix'], ['nomnoml','Nomnoml · UML 源码'], ['objective-c','Objective-C'],
    ['ocaml','OCaml'], ['octave','Octave'], ['pascal','Pascal / Delphi'],
    ['perl','Perl'], ['php','PHP'], ['plantuml','PlantUML · UML 源码'],
    ['plpgsql','PL/pgSQL'], ['postgresql','PostgreSQL'], ['powershell','PowerShell'],
    ['prolog','Prolog'], ['properties','Properties'], ['protobuf','Protocol Buffers'],
    ['pug','Pug / Jade'], ['python','Python'], ['r','R'], ['racket','Racket'],
    ['raku','Raku / Perl 6'], ['regex','Regular Expression'], ['robotframework','Robot Framework'],
    ['rst','reStructuredText'], ['ruby','Ruby'], ['rust','Rust'], ['sas','SAS'],
    ['sass','Sass'], ['scala','Scala'], ['scheme','Scheme'],
    ['scss','SCSS'], ['smalltalk','Smalltalk'], ['solidity','Solidity'],
    ['sparql','SPARQL'], ['sql','SQL'], ['sqlite3','SQLite'], ['stata','Stata'], ['svelte','Svelte'],
    ['swift','Swift'], ['tcl','Tcl'], ['toml','TOML'], ['tsql','T-SQL / SQL Server'], ['tsx','TSX / React'],
    ['turtle','Turtle / RDF'],
    ['typescript','TypeScript'], ['vala','Vala'], ['vb.net','Visual Basic .NET'],
    ['vbscript','VBScript'], ['verilog','Verilog / SystemVerilog'], ['vhdl','VHDL'], ['vim','Vim Script'],
    ['vue','Vue'], ['xml','XML / SVG'], ['yaml','YAML'], ['zig','Zig'],
    ['dot','Graphviz / DOT · 图表源码']];
  const aliases = {py:'python', js:'javascript', ts:'typescript', 'c++':'cpp',
    'c#':'csharp', cs:'csharp', sh:'bash', shell:'bash', text:'', plaintext:'', txt:'',
    md:'markdown', yml:'yaml', 'dockerfile':'docker', 'docker-compose':'yaml',
    k8s:'yaml', kubernetes:'yaml', tf:'hcl', terraform:'hcl', ps1:'powershell',
    pwsh:'powershell', cmd:'bat', rb:'ruby', rs:'rust', golang:'go', kt:'kotlin',
    tex:'latex', uml:'plantuml', puml:'plantuml', graphviz:'dot', cql:'cassandra',
    svg:'xml', proto:'protobuf', 'f#':'fsharp', objc:'objective-c',
    mdx:'markdown', zsh:'bash', console:'bash', 'c++11':'cpp', 'c++17':'cpp',
    'c++20':'cpp', 'c++23':'cpp', 'visual-basic':'vb.net', psql:'postgresql',
    sqlite:'sqlite3', sqlserver:'tsql', gql:'graphql', 'react':'jsx'};
  const aliasEntries=Object.entries(aliases);
  const pairs = {'(':')','[':']','{':'}','"':'"', "'":"'", '\u0060':'\u0060'};
  function language(lang) { lang=(lang||'').trim().toLowerCase(); return aliases[lang] ?? lang; }
  function suggestions(query) {
    const q=(query||'').trim().toLowerCase(), normalized=language(q);
    const rank=([value,label])=> {
      const words=label.toLowerCase();
      if(q && (value===q || value===normalized || words===q)) return 0;
      if(value.startsWith(q) || words.startsWith(q)) return 1;
      if(aliasEntries.some(([alias,target])=>target===value && alias.startsWith(q))) return 2;
      return value.includes(q)||words.includes(q)?3:4;
    };
    return languages.map(entry=>({entry,score:q?rank(entry):0}))
      .filter(({score})=>score<4)
      .sort((a,b)=>a.score-b.score||a.entry[0].localeCompare(b.entry[0]))
      .map(({entry})=>entry);
  }
  function unit(lang, fallback) {
    return ' '.repeat(['c','cpp','python','java','csharp','rust','go'].includes(language(lang))
      ? 4 : ['javascript','typescript','json','html','css'].includes(language(lang)) ? 2 : fallback || 2);
  }
  function context(text, lang) {
    let quote='', comment='', clean='';
    const hash=['python','bash'].includes(language(lang));
    const slash=['c','cpp','java','javascript','typescript','csharp','go','rust','css'].includes(language(lang));
    for (let i=0;i<text.length;i++) {
      const c=text[i], n=text[i+1];
      if (comment==='line') { if(c==='\n') {comment='';clean+='\n';} continue; }
      if (comment==='block') { if(c==='*'&&n==='/'){comment='';i++;} else if(c==='\n') clean+='\n'; continue; }
      if (quote) {
        if(c==='\\') {i++;continue;}
        if(c===quote) quote='';
        if(c==='\n') clean+='\n';
        continue;
      }
      if ((hash&&c==='#') || (slash&&c==='/'&&n==='/')) {comment='line';continue;}
      if(slash&&c==='/'&&n==='*'){comment='block';i++;continue;}
      if(c==='"'||c==="'"||c==='\u0060'){quote=c;continue;}
      clean+=c;
    }
    return {quote,comment,clean};
  }
  function newline(text,start,end,lang,size) {
    const before=text.slice(0,start), after=text.slice(end);
    const line=before.slice(before.lastIndexOf('\n')+1);
    const indent=(line.match(/^[ \t]*/)||[''])[0], ctx=context(before,lang);
    const cleanLine=ctx.clean.slice(ctx.clean.lastIndexOf('\n')+1).trimEnd();
    const open=cleanLine.slice(-1);
    const extra=!ctx.quote&&ctx.comment!=="block" && ((open!==''&&/[{[(]/.test(open)) ||
      language(lang)==='python' && cleanLine.endsWith(':')) ? unit(lang,size) : '';
    const closing={'{':'}','[':']','(':')'}[open];
    if (extra && closing && after.trimStart().startsWith(closing))
      return {start,end,text:'\n'+indent+extra+'\n'+indent,caret:start+1+indent.length+extra.length};
    return {start,end,text:'\n'+indent+extra,caret:start+1+indent.length+extra.length};
  }
  function tab(text,start,end,lang,size,reverse) {
    const step=unit(lang,size);
    if(start===end&&!reverse) return {start,end,text:step,caret:start+step.length};
    const a=start===0?0:text.lastIndexOf('\n',start-1)+1;
    const endpoint=end>start&&text[end-1]==='\n' ? end-1 : end;
    let b=text.indexOf('\n',endpoint); if(b<0)b=text.length;
    const lines=text.slice(a,b).split('\n');
    let first=0,total=0;
    const result=lines.map((line,i)=>{
      const removed=reverse?(line.startsWith('\t')?1:Math.min(step.length,(line.match(/^ */)||[''])[0].length)):0;
      const delta=reverse?-removed:step.length;
      if(i===0) first=delta;total+=delta;
      return reverse?line.slice(removed):step+line;
    }).join('\n');
    return {start:a,end:b,text:result,caret:Math.max(a,start+first),
      selectionEnd:start===end?undefined:Math.max(a,end+total)};
  }
  function pair(text,start,end,char,lang) {
    const ctx=context(text.slice(0,start),lang);
    if(start===end && text[start]===char && Object.values(pairs).includes(char) && !ctx.comment)
      return {skip:start+1};
    if(!pairs[char] || ctx.quote || ctx.comment) return null;
    if(start===end && (char==="'"||char==='"') && /[\w]/.test(text[start-1]||'')) return null;
    const selected=text.slice(start,end);
    return {start,end,text:char+selected+pairs[char],caret:start+1,
      selectionEnd:selected?start+1+selected.length:undefined};
  }
  return {languages,language,suggestions,unit,context,newline,tab,pair,pairs};
});
