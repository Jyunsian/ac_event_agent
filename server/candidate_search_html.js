const searchAudit=data.search||{},pruning=searchAudit.pruning||[];
grid(el('search-summary'),'本次搜尋摘要',['生成條件','合併後／預算前','實際評估','合併／排除紀錄'],[[searchAudit.enumerated,searchAudit.unique_before_cap,searchAudit.selected_count,pruning.length]]);
el('search-summary').append(node('p','固定起點窗口（小時）：'+text(searchAudit.searched_windows)));
let pruningPage=1;
const pruningLabels={MAX_CANDIDATES_LIMIT:'超出本次搜尋預算',EQUIVALENT_PREDICATE:'邏輯等價，合併重複條件',DIFFERENT_WINDOWS_NOT_COMPOSABLE:'不同窗口，不組合'};
function renderPruning(){
 const query=el('pruning-query').value.toLowerCase();
 const rows=pruning.filter(r=>(JSON.stringify(r)+' '+(pruningLabels[r.reason]||'')).toLowerCase().includes(query));
 pruningPage=Math.max(1,Math.min(pruningPage,Math.ceil(rows.length/50)));
 el('pruning-count').textContent='符合 '+rows.length+' / '+pruning.length+' 筆；第 '+pruningPage+' 頁，每頁50筆';
 const root=el('pruning-table');root.replaceChildren();
 for(const row of rows.slice((pruningPage-1)*50,pruningPage*50)){
  const item=document.createElement('details');
  item.append(node('summary',(pruningLabels[row.reason]||'其他處理原因')+' · '+(row.evaluation_status==='not_evaluated'?'未評估，不代表不支持':'合併／排除紀錄，不是驗證結果')));
  item.append(node('pre',row));root.append(item);
 }
 el('pruning-prev').disabled=pruningPage===1;el('pruning-next').disabled=pruningPage*50>=rows.length;
}
el('pruning-query').oninput=()=>{pruningPage=1;renderPruning();};
el('pruning-prev').onclick=()=>{pruningPage--;renderPruning();};
el('pruning-next').onclick=()=>{pruningPage++;renderPruning();};renderPruning();
