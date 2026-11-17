const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://localhost:8000/experiments/2015/more');
  assert.equal(await page.locator('tbody tr').count(),30);
  const response=await page.request.get('http://localhost:8000/experiments/curation-2015-round2/progress.json');
  assert.equal(response.status(),200);const progress=await response.json();
  assert.match(await page.locator('main>p').first().innerText(),new RegExp(`${progress.source_records}/30 source records`));
  assert.match(await page.locator('main>p').first().innerText(),new RegExp(`${progress.reviewed_reading_cones_complete}/30 reviewed reading cones complete`));
  for(const href of await page.locator('a[href^="/experiments/"],a[href^="/curation/source-tasks/"]').evaluateAll(as=>as.map(a=>a.getAttribute('href')))){
    assert.equal((await page.request.get('http://localhost:8000'+href)).status(),200,href);
  }
  const sources=await page.locator('tbody a[href^="/#source/"]').evaluateAll(as=>as.map(a=>({href:a.getAttribute('href'),title:a.textContent.replace(/\s+/g,' ').trim()})));
  assert.equal(sources.length,progress.source_records);
  await page.goto('http://localhost:8000'+sources[0].href);
  await page.setViewportSize({width:390,height:844});
  for(const source of sources){
    await page.evaluate(hash=>{location.hash=hash;},new URL(source.href,'http://localhost:8000').hash);
    await page.waitForFunction(title=>document.title.replace(/\s+/g,' ').trim()===title+' · The Shape of Math',source.title);
    await page.locator('.coverage-note').waitFor();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),source.href);
  }
  assert.deepEqual(errors,[]);await browser.close();
  console.log('Additional sources:30 rows, actual review counts, all report links and all source pages on mobile pass.');
})().catch(e=>{console.error(e);process.exit(1);});
