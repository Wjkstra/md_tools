/* Offline language-aware text edits. DOM changes stay in Chromium's undo stack. */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.CodeEditing = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  const languages = [['', '纯文本'], ['c','C'], ['cpp','C++'], ['python','Python'],
    ['javascript','JavaScript'], ['typescript','TypeScript'], ['json','JSON'],
    ['html','HTML'], ['css','CSS'], ['java','Java'], ['csharp','C#'],
    ['go','Go'], ['rust','Rust'], ['bash','Shell'], ['sql','SQL']];
  const aliases = {py:'python', js:'javascript', ts:'typescript', 'c++':'cpp',
    'c#':'csharp', cs:'csharp', sh:'bash', shell:'bash', text:'', plaintext:''};
  const pairs = {'(':')','[':']','{':'}','"':'"', "'":"'", '\u0060':'\u0060'};
  function language(lang) { lang=(lang||'').toLowerCase(); return aliases[lang] ?? lang; }
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
  return {languages,language,unit,context,newline,tab,pair,pairs};
});
