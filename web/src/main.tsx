import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Workspace } from './workspace';
import { UploadPage } from './upload-page';
import { RunPage, HistoryPage } from './run-page';
import './style.css';
const runId = location.pathname.startsWith('/runs/') ? location.pathname.slice(6) : new URLSearchParams(location.search).get('run');
const page = location.pathname === '/upload' ? <UploadPage/> : location.pathname === '/history' ? <HistoryPage/> : runId ? <RunPage id={runId} workspace={location.pathname === '/workspace'}/> : <Workspace/>;
createRoot(document.getElementById('root')!).render(<StrictMode>{page}</StrictMode>);
