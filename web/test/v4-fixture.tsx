import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ReportPanel} from '../src/report-panel';
import '../src/style.css';
const p=new URLSearchParams(location.search);
function Fixture(){
 const [view,setView]=useState({hours:24,cohort:'observation'});
 return <main style={{maxWidth:1100,margin:'auto',padding:16,minWidth:0}}><p>合成資料 · V4 報告互動測試</p><output aria-label="聊天選取上下文">{JSON.stringify(view)}</output><ReportPanel onViewChange={setView} run={{run_id:p.get('run')!,dataset_id:p.get('dataset')!,report_version:1} as any} tab={p.get('tab')??'overview'}/></main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
