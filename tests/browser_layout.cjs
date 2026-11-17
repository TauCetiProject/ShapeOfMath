// Read-only layout regression checks against a running server.
// Requires Playwright and its Chromium browser. Set MATHDB_BASE_URL to select
// another server; NODE_PATH can point to an existing Playwright installation.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const { chromium } = require('playwright');
const base = process.env.MATHDB_BASE_URL || 'http://127.0.0.1:8000';

async function graphGeometry(page) {
  const problems = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.graph-node')];
    const paths = [...document.querySelectorAll('.connections > path[data-node]')];
    const obstacles = [...cards, ...document.querySelectorAll('.graph .more-button')]
      .map(el => ({ text: el.innerText, r: el.getBoundingClientRect() }));
    const problems = [];
    if (paths.length !== cards.length) problems.push('Missing node connections');
    for (const path of paths) {
      const matrix = path.getScreenCTM(), length = path.getTotalLength();
      for (let i = 1; i < 200; i++) {
        const point = path.getPointAtLength(length * i / 200);
        const x = matrix.a * point.x + matrix.c * point.y + matrix.e;
        const y = matrix.b * point.x + matrix.d * point.y + matrix.f;
        for (const { text, r } of obstacles) {
          if (x > r.left + 2 && x < r.right - 2 && y > r.top + 2 && y < r.bottom - 2) {
            problems.push('Connection crosses ' + text);
            break;
          }
        }
      }
    }
    for (const card of cards) {
      const r = card.getBoundingClientRect();
      for (const control of card.querySelectorAll('button')) {
        const b = control.getBoundingClientRect();
        if (b.left < r.left || b.right > r.right || b.top < r.top || b.bottom > r.bottom)
          problems.push('Card control outside its border');
      }
    }
    return [...new Set(problems)];
  });
  assert.deepEqual(problems, []);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let views = 0;
    for (const width of [320, 390, 768, 1024, 1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const slug of ['fusion-category', 'cauchy-schwarz-inner-product']) {
        await page.goto(base + '/#concept/' + slug, { waitUntil: 'networkidle' });
        await page.waitForFunction(() => document.querySelector('.connections > path[data-node]'));
        await graphGeometry(page);
        if (slug === 'fusion-category') {
          assert.equal(await page.locator('.concept-summary').evaluate(el => {
            const r = el.getBoundingClientRect();
            return r.top >= document.querySelector('.masthead').getBoundingClientRect().bottom && r.bottom <= innerHeight;
          }), true, 'The definition must be visible before dependents');
        }
        if (slug === 'fusion-category') {
          await page.locator('[data-action="expand"][data-direction="up"]').click();
          await page.waitForTimeout(50);
          await graphGeometry(page);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        if (width <= 720) {
          const header = await page.evaluate(() => {
            const r = document.querySelector('.brand-symbol').getBoundingClientRect();
            const header = document.querySelector('.masthead').getBoundingClientRect();
            const main = document.querySelector('.app-shell').getBoundingClientRect();
            const controls = [...document.querySelectorAll('.masthead-right a,.masthead-right button')]
              .map(el => el.getBoundingClientRect());
            return { round: Math.abs(r.width - r.height) < 1, below: main.top >= header.bottom,
              visible: controls.every(b => b.width > 0 && b.left >= 0 && b.right <= innerWidth) };
          });
          assert.deepEqual(header, { round: true, below: true, visible: true });
          await page.locator('#toggle-nav').click();
          assert.equal(await page.evaluate(() => Math.abs(document.querySelector('.sidebar').getBoundingClientRect().top -
            document.querySelector('.masthead').getBoundingClientRect().bottom) < 1), true);
          await page.locator('#toggle-nav').click();
        }
        views++;
      }
      await page.goto(base + '/experiments/2015', { waitUntil: 'networkidle' });
      assert.equal(await page.locator('tbody tr').count(), 30);
      if (width <= 720) {
        assert.equal(await page.locator('tbody td').evaluateAll(cells => cells.every(el => {
          const r = el.getBoundingClientRect();
          return r.left >= 0 && r.right <= innerWidth && el.scrollWidth <= el.clientWidth + 1;
        })), true, 'Every mobile table cell must fit without horizontal scrolling');
      }
      views++;
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + '/#concept/group', { waitUntil: 'networkidle' });
    assert.equal(await page.locator('.file-name').evaluateAll(names => names.every(el =>
      el.getBoundingClientRect().height < parseFloat(getComputedStyle(el).lineHeight) * 1.5)), true);
    await page.goto(base + '/#source/morrison-snyder-2012', { waitUntil: 'networkidle' });
    assert.equal(await page.locator('.concept-columns').evaluate(el =>
      el.children[1].getBoundingClientRect().bottom < el.children[0].getBoundingClientRect().bottom - 100), true);

    await page.goto(base + '/#concept/drinfeld-center?view=cone', { waitUntil: 'networkidle' });
    await page.locator('.cone-root').waitFor();
    assert.equal(await page.locator('#cone-zoom').innerText(), '100%');
    await page.getByRole('button', { name: 'Fit all', exact: true }).click();
    assert.equal(await page.locator('.cone-viewport').evaluate(el => {
      const v = el.getBoundingClientRect(), world = el.querySelector('.cone-world').getBoundingClientRect();
      return world.left >= v.left && world.right <= v.right && world.top >= v.top && world.bottom <= v.bottom;
    }), true);
    await page.getByRole('button', { name: 'View graph at 100 percent' }).click();
    await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    const zoom = await page.locator('#cone-zoom').innerText();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(150);
    await page.getByRole('button', { name: 'Diagram', exact: true }).click();
    assert.equal(await page.locator('#cone-zoom').innerText(), zoom, 'Resize must preserve a custom zoom');
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(await page.locator('.cone-panel').getAttribute('data-display'), 'list');
    const listIds = await page.locator('.cone-list-node').evaluateAll(nodes => nodes.map(n => n.dataset.conceptId));
    assert.equal(new Set(listIds).size, listIds.length, 'Outline must show every concept once');
    assert.equal(listIds.length, await page.locator('.cone-node').count(), 'Outline and diagram must agree');
    assert.equal(await page.locator('.cone-list-node').evaluateAll(nodes => nodes.every(el => {
      const r = el.getBoundingClientRect();
      return r.left >= 0 && r.right <= innerWidth && el.scrollWidth <= el.clientWidth + 1;
    })), true, 'Mobile outline cards must fit without sideways panning');
    await page.getByRole('button', { name: 'Diagram', exact: true }).click();
    assert.equal(await page.locator('#cone-zoom').innerText(), '100%');
    const viewport = page.locator('.cone-viewport');
    await viewport.scrollIntoViewIfNeeded();
    const box = await viewport.boundingBox(), before = await page.locator('.cone-world').getAttribute('transform');
    await page.mouse.move(box.x + 8, box.y + 8);
    await page.mouse.down();
    await page.mouse.move(box.x + 48, box.y + 48);
    await page.mouse.up();
    assert.notEqual(await page.locator('.cone-world').getAttribute('transform'), before, 'Pan must move the graph');
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Save SVG', exact: true }).click();
    const download = await downloading;
    const svg = await fs.readFile(await download.path(), 'utf8');
    assert.match(svg, /viewBox="0 0 \d+ \d+"/);
    assert.match(svg, /font-size="13"/);
    assert.doesNotMatch(svg, /class="cone-world" transform=/, 'Export must include the whole graph');
    assert.match(svg, /href="http[^\"]+\/#concept\//);

    // Long formulas and narrower panels must not overlap neighboring controls.
    for (const width of [390, 721, 768, 860, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + '/#source/saroglou-zvavitch-2015', { waitUntil: 'networkidle' });
      assert.equal(await page.locator('.concept-row p').evaluateAll(items => items.every(el =>
        el.scrollWidth <= el.clientWidth + 1)), true, 'Source formula overflow');
      if (width < 1024) {
        assert.equal(await page.locator('.concept-columns').evaluate(el =>
          el.children[1].getBoundingClientRect().top >= el.children[0].getBoundingClientRect().bottom), true);
      }
    }

    // Every long cone edge must use empty routing slots, including offscreen
    // nodes. Testing only the initial viewport misses the old overlap bug.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(base + '/#concept/chebyshev-inequality?view=cone&mode=proof', { waitUntil: 'networkidle' });
    const data = await (await page.request.get(base + '/api/v1/state')).json();
    const crossings = await page.evaluate(edges => {
      const nodes = [...document.querySelectorAll('.cone-node')].map(el => ({
        id: el.dataset.conceptId, rect: el.querySelector('rect').getBoundingClientRect()
      }));
      const crossings = [];
      for (const path of document.querySelectorAll('.cone-edge')) {
        const edge = edges.find(e => String(e.id) === path.dataset.edgeId);
        const matrix = path.getScreenCTM(), length = path.getTotalLength();
        for (let i = 1; i < 400; i++) {
          const p = path.getPointAtLength(length * i / 400);
          const x = matrix.a * p.x + matrix.c * p.y + matrix.e;
          const y = matrix.b * p.x + matrix.d * p.y + matrix.f;
          for (const { id, rect: r } of nodes) {
            if (id !== edge.dependent_id && id !== edge.prerequisite_id &&
                x > r.left + 2 && x < r.right - 2 && y > r.top + 2 && y < r.bottom - 2) {
              crossings.push({ edge: edge.id, node: id });
              break;
            }
          }
        }
      }
      return crossings;
    }, data.data.concept_dependency);
    assert.deepEqual(crossings, []);

    // Script notation is rendered from text nodes, preserving escaping and
    // leaving unsupported/unbalanced input readable. Repeated renders are safe.
    const formatting = await page.evaluate(() => {
      const root = document.createElement('div');
      const p = document.createElement('p');root.className = 'concept-summary';root.append(p);
      p.textContent = 'W^{1,1}, x_{i_{j}}, ∑_j a_j^q, C_c^∞, broken^{, <img src=x onerror=alert(1)>';
      document.body.append(root);MathText.render(root);const first = root.innerHTML;MathText.render(root);
      const stable = first === root.innerHTML;
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      const node = document.createElementNS(svg.namespaceURI, 'g');node.classList.add('cone-node');
      const label = document.createElementNS(svg.namespaceURI, 'text');label.textContent = 'W^{1,1}';
      node.append(label);svg.append(node);root.append(svg);MathText.render(root);
      const result = { stable, supers: root.querySelectorAll('sup').length,
        nested: !!root.querySelector('sub sub'), html: root.querySelectorAll('img,script').length,
        kept: root.textContent.includes('broken^{'), svg: label.querySelector('tspan')?.getAttribute('baseline-shift') };
      root.remove();return result;
    });
    assert.deepEqual(formatting, { stable: true, supers: 3, nested: true, html: 0, kept: true, svg: 'super' });
    await page.goto(base + '/experiments/2015', { waitUntil: 'networkidle' });
    assert.ok(await page.locator('td sup.math-script').count(), 'Sample titles must typeset braced exponents');
    assert.deepEqual(errors, []);
    console.log(`${views} responsive views passed, plus visible definitions, formulas, cone routing and outline, zoom, resize, pan and SVG export.`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
