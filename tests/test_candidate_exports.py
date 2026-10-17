from server.candidate_exports import csv_cell


def test_offline_html_embeds_exact_evidence_without_script_injection():
    import json
    from server.candidate_html import render_candidate_html
    payload={'details':[],'entries':[], 'export':{'synthetic':True},
             'search':{'untrusted':'</script><script>alert(1)</script>&<>'}}
    raw=render_candidate_html(payload).decode()
    encoded=raw.split('<script id="evidence" type="application/json">')[1].split('</script>')[0]
    recovered=json.loads(encoded)
    assert recovered['search']==payload['search']
    assert '<script>alert(1)' not in raw
    assert "connect-src 'none'" in raw
    assert 'fetch(' not in raw and 'src="http' not in raw


def test_offline_html_browser_paging_search_and_detail(tmp_path):
    import subprocess
    from server.candidate_html import render_candidate_html
    details=[];entries=[]
    for index in range(51):
        identity=f'{index:064x}'
        details.append({'candidate_id':identity,'event_spec':{'origin':'first_open','window_hours':6,
            'predicate':{'op':'revenue_sum','threshold':index+1}},'validation':{'metrics':None},
            'exploration':{},'selection':{},'timing_status':'observed'})
        entries.append({'candidate_id':identity,'window_hours':6,'detail_sha256':'a'*64,'evidence_status':'insufficient_data','reasons':[],
                        'summary':{'event_spec':details[-1]['event_spec'],'difference_usd':-index,'coverage':.5,
                                   'triggered_users':10,'untriggered_users':10}})
    path=tmp_path/'offline.html'
    path.write_bytes(render_candidate_html({'entries':entries,'details':details,'search':{'pruning':[{'reason':'MAX_CANDIDATES_LIMIT','evaluation_status':'not_evaluated','candidate_id':str(i)} for i in range(51)]},
        'export':{'synthetic':True,'export_scope':'complete','evaluated_count':51,'exported_count':51}}))
    script="""
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true,channel:'chrome'});
try {
 const context=await browser.newContext({offline:true});const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.argv[1]);
 assert.equal(await page.locator('#pruning-table details').count(),50);
 await page.locator('#pruning-next').click();assert.equal(await page.locator('#pruning-table details').count(),1);
 await page.locator('#pruning-query').fill('不存在');assert.equal(await page.locator('#pruning-table details').count(),0);
 await page.locator('#pruning-query').fill('超出本次搜尋預算');assert.equal(await page.locator('#pruning-table details').count(),50);
 const plots=page.locator('#income-plots svg');assert.equal(await plots.count(),2);
 assert.equal(await plots.nth(0).getAttribute('data-x-min'),await plots.nth(1).getAttribute('data-x-min'));
 assert.equal(await plots.nth(0).getAttribute('data-x-max'),await plots.nth(1).getAttribute('data-x-max'));
 await plots.nth(1).locator('circle').first().focus();await page.keyboard.press('Enter');
 assert.equal(await page.locator('#card').isVisible(),true);
 assert.equal(await page.locator('#rows tr').count(),50);
 await page.locator('#next').click();assert.equal(await page.locator('#rows tr').count(),1);
 await page.locator('#rows button').click();assert.equal(await page.locator('#card').isVisible(),true);
 assert.match(await page.locator('#card').innerText(),/凍結家族統計檢驗/);
 assert.match(await page.locator('#card').innerText(),/未知／此版本未計算/);
 await page.locator('#search').fill('不存在');assert.equal(await page.locator('#rows tr').count(),0);
 await page.locator('#search').fill('');assert.equal(await page.locator('#rows tr').count(),50);
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 assert.deepEqual(errors,[]);
} finally {await browser.close();}
"""
    result=subprocess.run(['node','--input-type=module','-e',script,path.as_uri()],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr


def test_csv_keeps_numeric_negative_differences_and_protects_text():
    assert csv_cell(-.001)==-.001
    assert csv_cell(0)==0
    assert csv_cell(None)==''
    for value in ('=1+1','+cmd','-cmd','@SUM(A1)','  =1+1','\t=1+1'):
        assert csv_cell(value)=="'"+value
    assert csv_cell('首次開啟後前6小時')=='首次開啟後前6小時'
