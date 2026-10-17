import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {AssistantMessage} from '../src/assistant-message';
import '../src/style.css';
import '../src/chat-panel.css';
const ref='report:00000000-0000-0000-0000-000000000001#/summary';
const content=['## 先看結論','目前樣本不足，**不能判定投放會提升**。','',
  '- 符合條件：2 位用戶','- 平均收益：0.00000001 美元','',
  '| 比較項目 | 數值 |','| --- | --- |','| 前 7 天收益 | 0.00000001 美元 |','| 未提供的資料 | 未知 |','',
  `[來源](${ref})`,`**${ref}**`,`\`${ref}\``,'report:00000000-0000-0000-0000-000000000002#/summary','',
  '<img src=x onerror="window.__injected=1">','[惡意連結](javascript:window.__injected=1)','',
  '```html','<script>window.__injected=1</script>','```','',
  '這是很長的合成回覆，檢查手機閱讀與換行，不是實際分析建議。'.repeat(30)].join('\n');
function Fixture(){const [selected,setSelected]=useState('');return <main style={{maxWidth:640,padding:20,margin:'auto'}}><h1>合成回覆呈現測試</h1><AssistantMessage content={content} canReference={value=>value===ref} onReference={setSelected}/><output aria-label="已選證據">{selected}</output></main>;}
createRoot(document.getElementById('root')!).render(<Fixture/>);
