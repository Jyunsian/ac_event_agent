// Deliberately limited Markdown. No HTML, images, executable links or plugins.
export type Block={kind:'paragraph'|'heading'|'quote'|'code'|'list'|'table';lines:string[];ordered?:boolean};
export function tableCells(line:string):string[]{return line.trim().replace(/^\|/,'').replace(/\|$/,'').split(/(?<!\\)\|/).map(cell=>cell.trim().replace(/\\\|/g,'|'));}
export function messageBlocks(content:string):Block[]{
  const lines=content.replace(/\r\n?/g,'\n').split('\n'),blocks:Block[]=[];
  for(let i=0;i<lines.length;){
    const line=lines[i];if(!line.trim()){i++;continue;}
    if(/^\s*```/.test(line)){const code:string[]=[];i++;while(i<lines.length&&!/^\s*```/.test(lines[i]))code.push(lines[i++]);if(i<lines.length)i++;blocks.push({kind:'code',lines:code});continue;}
    if(line.includes('|')&&i+1<lines.length){
      const header=tableCells(line),divider=tableCells(lines[i+1]);
      if(header.length===divider.length&&divider.every(cell=>/^:?-{3,}:?$/.test(cell))){
        const rows=[line];i+=2;while(i<lines.length&&lines[i].includes('|')&&tableCells(lines[i]).length===header.length)rows.push(lines[i++]);
        blocks.push({kind:'table',lines:rows});continue;
      }
    }
    const heading=line.match(/^#{1,6}\s+(.+)$/);if(heading){blocks.push({kind:'heading',lines:[heading[1]]});i++;continue;}
    if(/^>\s?/.test(line)){blocks.push({kind:'quote',lines:[line.replace(/^>\s?/,'')]});i++;continue;}
    const list=line.match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);
    if(list){const ordered=!!list[2],items:string[]=[];while(i<lines.length){const item=lines[i].match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);if(!item||!!item[2]!==ordered)break;items.push(item[3]);i++;}blocks.push({kind:'list',lines:items,ordered});continue;}
    const text=[line];i++;while(i<lines.length&&lines[i].trim()&&!/^\s*(?:```|#{1,6}\s|>\s?|[-+*]\s|\d+\.\s)/.test(lines[i]))text.push(lines[i++]);blocks.push({kind:'paragraph',lines:text});
  }
  return blocks;
}
export type Inline={kind:'text'|'strong'|'em'|'code'|'reference';text:string};
export function inlineParts(text:string):Inline[]{
  const pattern=/\[[^\]\n]*\]\((report:[^\s<>"'`()\[\]，。；（）、]+)\)|report:[^\s<>"'`()\[\]，。；（）、]+|\*\*([^*\n]+)\*\*|`([^`\n]+)`|\*([^*\n]+)\*/g;
  const parts:Inline[]=[];let cursor=0;
  for(const match of text.matchAll(pattern)){
    if(match.index!>cursor)parts.push({kind:'text',text:text.slice(cursor,match.index)});
    const token=match[0];
    if(match[1]||token.startsWith('report:')){const value=(match[1]||token).replace(/[.,;]+$/,'');parts.push({kind:'reference',text:value});if(!match[1]&&value.length<token.length)parts.push({kind:'text',text:token.slice(value.length)});}
    else parts.push({kind:match[2]?'strong':match[3]?'code':'em',text:match[2]||match[3]||match[4]});
    cursor=match.index!+token.length;
  }
  if(cursor<text.length)parts.push({kind:'text',text:text.slice(cursor)});return parts;
}
