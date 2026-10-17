import labels from '../../contracts/reason_labels.json' with {type:'json'};
export function reasonText(code:string):string {return (labels as Record<string,string>)[code]??'另有尚待確認的資料或分析限制，請查看詳細資料或詢問助理。';}
export function reasonsText(codes:string[]):string {return [...new Set(codes.map(reasonText))].join('；');}
export function displayNumber(v:number,unit=''):string {
  if(!Number.isFinite(v))return '未知';
  const n=unit==='%'?v*100:unit==='h'?v/3600:v;
  const digits=unit==='USD'?6:2;
  const rounded=Number(n.toFixed(digits));
  const text=n!==0&&rounded===0?n.toPrecision(3):new Intl.NumberFormat('zh-TW',{maximumFractionDigits:digits}).format(n);
  return text+(unit==='h'?' 小時':unit==='USD'?' 美元':unit);
}
