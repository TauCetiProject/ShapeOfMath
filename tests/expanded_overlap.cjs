const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://localhost:8000/experiments/2015/overlap/expanded');
  await page.locator('.chart').first().waitFor();
  assert.equal(await page.locator('.chart').count(),4);
  assert.match(await page.locator('#scope-note').innerText(),/1501\.01654.*1503\.07110/);
  await page.locator('circle[data-group="combined"][data-n="59"]').focus();
  assert.match(await page.locator('#point-detail').innerText(),/82\.4%/);
  await page.locator('circle[data-group="combined"][data-n="0"]').focus();
  assert.match(await page.locator('#point-detail').innerText(),/mean 0%/);
  const data=await (await page.request.get('http://localhost:8000/experiments/curation-2015-round2/overlap/results.json')).json();
  for(const dataset of ['all60','reviewed58','first30','next30']){
    await page.locator('#dataset').selectOption(dataset);
    assert.equal(await page.locator('#summary tr').count(),4);
    if(dataset==='reviewed58'){
      assert.match(await page.locator('#scope-note').innerText(),/nonrandom/);
      assert.match(await page.locator('.chart').nth(1).locator('h3').innerText(),/19 papers/);
    }
    for(const metric of ['known','marginal','cumulative']){
      await page.locator('#metric').selectOption(metric);
      const r=data.datasets[dataset].groups.combined;
      await page.locator(`circle[data-group="combined"][data-n="${r.paper_count-1}"]`).focus();
      const mean=metric==='known'?r.mean_known.at(-1)*100:metric==='marginal'?r.mean_marginal.at(-1):r.mean_cumulative.at(-1);
      const value=mean.toLocaleString('en-US',{maximumFractionDigits:1})+(metric==='known'?'%':'');
      assert.ok((await page.locator('#point-detail').innerText()).includes('mean '+value));
      for(const id of ['png','svg','pdf']){
        const path=await page.locator('#'+id).getAttribute('href');
        assert.equal((await page.request.get('http://localhost:8000'+path)).status(),200,path);
      }
    }
  }
  await page.locator('#dataset').selectOption('all60');await page.locator('#metric').selectOption('known');
  await page.locator('#example').check();await page.locator('#order').selectOption({value:'3'});
  await page.waitForFunction(()=>document.getElementById('order').value==='3');
  await page.locator('circle[data-group="combined"][data-n="0"]').focus();
  assert.match(await page.locator('#point-detail').innerText(),/Example 4:.*already known/);
  await page.locator('#group').selectOption('math.NT');assert.equal(await page.locator('.chart').count(),1);
  await page.reload();await page.locator('.chart').waitFor();
  assert.equal(await page.locator('#group').inputValue(),'math.NT');
  assert.equal(await page.locator('#metric').inputValue(),'known');
  await page.locator('#group').selectOption('all');
  for(const path of new Set(await page.locator('a[href^="/experiments/"]').evaluateAll(as=>as.map(a=>a.getAttribute('href'))))){
    assert.equal((await page.request.get('http://localhost:8000'+path)).status(),200,path);
  }
  assert.equal((await page.request.get('http://localhost:8000/experiments/curation-2015-round2/overlap/model.py')).status(),404);
  await page.screenshot({path:'/tmp/shape-math-browser/expanded-overlap-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:'/tmp/shape-math-browser/expanded-overlap-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);await browser.close();
  console.log('Expanded overlap: all datasets/metrics, exact percentage endpoints, example order, URL state, figures/downloads, private-script 404 and mobile pass.');
})().catch(error=>{console.error(error);process.exit(1);});
