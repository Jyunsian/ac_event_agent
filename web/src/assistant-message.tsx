import {messageBlocks,inlineParts,tableCells} from './message-format';

export function AssistantMessage({content,onReference,canReference}:{content:string;onReference:(reference:string)=>void;canReference:(reference:string)=>boolean}){
  const references:string[]=[];
  function inline(text:string,depth=0):React.ReactNode{return inlineParts(text).map((part,i)=>{
    if(part.kind==='reference'){
      if(!canReference(part.text))return <span className="reference-unavailable" key={i}>（這項引用的來源尚無法確認）</span>;
      if(!references.includes(part.text))references.push(part.text);
      const number=references.indexOf(part.text)+1;
      return <button className="reference-button" key={i} aria-label={`查看證據 ${number}`} title={`查看證據 ${number}`} onClick={()=>onReference(part.text)}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 10.5 10.5 5.5M6.75 4.25l1.1-1.1a2.83 2.83 0 0 1 4 4l-1.1 1.1M9.25 11.75l-1.1 1.1a2.83 2.83 0 0 1-4-4l1.1-1.1"/></svg><span>{number}</span></button>;
    }
    const children=depth<3&&part.kind!=='text'?inline(part.text,depth+1):part.text;
    if(part.kind==='strong')return <strong key={i}>{children}</strong>;
    if(part.kind==='em')return <em key={i}>{children}</em>;
    if(part.kind==='code')return <code key={i}>{children}</code>;
    return part.text;
  });}
  return <><div className="assistant-content">{messageBlocks(content).map((block,i)=>{
    if(block.kind==='code'){
      const code=block.lines.join('\n');
      const refs=inlineParts(code).filter(part=>part.kind==='reference');
      return <div key={i}>{refs.map((part,j)=><span key={j}>{inline(part.text)}</span>)}<details><summary>查看補充設定或程式內容</summary><pre><code>{code}</code></pre></details></div>;
    }
    if(block.kind==='heading')return <h4 key={i}>{inline(block.lines[0])}</h4>;
    if(block.kind==='quote')return <blockquote key={i}>{inline(block.lines[0])}</blockquote>;
    if(block.kind==='table')return <div className="data-table" role="region" aria-label="回覆中的比較表" tabIndex={0} key={i}><table><thead><tr>{tableCells(block.lines[0]).map((cell,j)=><th scope="col" key={j}>{inline(cell)}</th>)}</tr></thead><tbody>{block.lines.slice(1).map((line,j)=><tr key={j}>{tableCells(line).map((cell,k)=><td key={k}>{inline(cell)}</td>)}</tr>)}</tbody></table></div>;
    if(block.kind==='list'){const items=block.lines.map((line,j)=><li key={j}>{inline(line)}</li>);return block.ordered?<ol key={i}>{items}</ol>:<ul key={i}>{items}</ul>;}
    return <p key={i}>{inline(block.lines.join('\n'))}</p>;
  })}</div><details className="message-original"><summary>查看原始回覆與引用</summary><pre>{content}</pre></details></>;
}
