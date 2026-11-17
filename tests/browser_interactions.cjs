// Read-only regression checks for dialogs, mobile navigation and cone outlines.
// Run against the local server with Playwright available, like browser_layout.cjs.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.MATHDB_BASE_URL || 'http://127.0.0.1:8000';

async function dialogControls(page, form = true) {
  assert.equal(await page.locator('#editor').evaluate((dialog, form) => {
    const bounds = dialog.getBoundingClientRect();
    const selectors = form ? ['.dialog-header button', '.form-footer .secondary-button', '[type="submit"]']
      : ['.dialog-header button'];
    return selectors.every(selector => {
      const rect = dialog.querySelector(selector).getBoundingClientRect();
      return rect.top >= bounds.top && rect.bottom <= bounds.bottom && rect.left >= bounds.left &&
        rect.right <= bounds.right && rect.top >= 0 && rect.bottom <= innerHeight;
    });
  }, form), true, 'Dialog controls must remain visible while content scrolls');
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/v1/**', route => {
      if (route.request().method() !== 'GET') {
        writes.push(route.request().url());return route.abort();
      }
      return route.continue();
    });
    for (const [width, height] of [[320, 568], [390, 844], [844, 390], [1440, 900]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base + '/#concept/group', { waitUntil: 'networkidle' });
      await page.locator('[data-action="edit-formalization"]').first().click();
      assert.equal(await page.locator('.form-body').evaluate(el => el.scrollHeight > el.clientHeight), true);
      for (const fraction of [0, 0.5, 1]) {
        await page.locator('.form-body').evaluate((el, fraction) => { el.scrollTop = el.scrollHeight * fraction; }, fraction);
        await dialogControls(page);
      }
      await page.getByRole('button', { name: 'Save changes', exact: true }).click();
      assert.equal(await page.locator('#field-reason').evaluate(el => el === document.activeElement), true,
        'Native validation should focus the required reason inside the scrolling body');
      await dialogControls(page);
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      assert.equal(await page.locator('#editor').evaluate(el => el.open), false);
      await page.locator('#history-button').click();
      await page.locator('.history-event').first().waitFor();
      await page.locator('.dialog-body').evaluate(el => { el.scrollTop = el.scrollHeight; });
      await dialogControls(page, false);
      await page.getByRole('button', { name: 'Close history' }).click();
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + '/#concept/group', { waitUntil: 'networkidle' });
    const toggle = page.locator('#toggle-nav');
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'search');
    assert.equal(await page.locator('#main').evaluate(el => el.inert), true);
    await page.locator('#main').evaluate(el => el.focus());
    assert.equal(await page.evaluate(() => document.activeElement.id), 'search', 'The obscured page must be inert');
    await toggle.focus();await page.keyboard.press('Shift+Tab');
    assert.equal(await page.evaluate(() => document.activeElement.closest('.sidebar') !== null), true);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'toggle-nav', 'Tab must wrap inside drawer controls');
    await page.keyboard.press('Escape');
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'toggle-nav');
    assert.equal(await page.locator('#main').evaluate(el => el.inert), false);
    await toggle.click();await page.mouse.click(365, 400);
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false', 'Tapping the backdrop must dismiss navigation');
    await page.keyboard.press('/');
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
    await page.locator('#search').fill('Abelian group');
    await page.locator('.record-item[data-slug="abelian-group"]').click();
    await page.waitForURL(/#concept\/abelian-group/);
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('#main').evaluate(el => el.inert), false);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'main');
    await toggle.click();await page.setViewportSize({ width: 1280, height: 900 });
    assert.equal(await page.locator('.sidebar').evaluate(el => el.inert), false);
    assert.equal(await page.locator('#main').evaluate(el => el.inert), false);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + '/#concept/chebyshev-inequality?view=cone&mode=proof', { waitUntil: 'networkidle' });
    assert.equal(await page.locator('.cone-list-level[open]').count(), 2);
    const initialHeight = await page.locator('.cone-list').evaluate(el => el.scrollHeight);
    const jump = page.getByRole('combobox', { name: 'Jump to outline level' });
    const url = page.url();
    await jump.selectOption('10');
    const level = page.locator('.cone-list-level[data-depth="10"]');
    assert.equal(await level.evaluate(el => el.open), true);
    assert.equal(page.url(), url, 'Jumping within an outline must preserve the selected concept URL');
    assert.equal(await level.evaluate(el => {
      const nav = document.querySelector('.cone-outline-nav').getBoundingClientRect();
      const header = document.querySelector('.masthead').getBoundingClientRect();
      const summary = el.querySelector('summary').getBoundingClientRect();
      return nav.top >= header.bottom - 1 && summary.top >= nav.bottom && summary.bottom <= innerHeight;
    }), true, 'Jumped-to level must appear below the sticky navigation');
    await page.getByRole('button', { name: 'Expand all', exact: true }).click();
    assert.equal(await page.locator('.cone-list-level[open]').count(), await page.locator('.cone-list-level').count());
    const fullHeight = await page.locator('.cone-list').evaluate(el => el.scrollHeight);
    assert.ok(initialHeight < fullHeight / 2, 'Default collapsed levels must substantially reduce scrolling');
    await page.getByRole('button', { name: 'Collapse levels', exact: true }).click();
    assert.equal(await page.locator('.cone-list-level[open]').count(), 1);
    await jump.selectOption('17');
    await page.getByRole('button', { name: 'Back to start ↑' }).click();
    assert.equal(await jump.inputValue(), '0');
    assert.equal(await page.locator('.cone-list-level[data-depth="0"]').evaluate(el => {
      const r = el.querySelector('summary').getBoundingClientRect();return r.top >= 0 && r.bottom <= innerHeight;
    }), true);

    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(base + '/#concept/fusion-category', { waitUntil: 'networkidle' });
    assert.equal(await page.locator('.concept-summary p').evaluate(el =>
      el.getBoundingClientRect().width < el.parentElement.getBoundingClientRect().width * 0.6), true);
    const scripts = await page.evaluate(() => {
      const root = document.createElement('div');root.className = 'concept-summary';
      const p = document.createElement('p');root.append(p);
      p.textContent = 'x^(−d−1), y_(i+(j)), z^-12, a_123, b^{i_(j)}, broken^(x, mismatch^{x), <img src=x>';
      document.body.append(root);MathText.render(root);const first = root.innerHTML;MathText.render(root);
      const result = { supers: [...root.querySelectorAll('sup')].map(el => el.textContent),
        subs: [...root.querySelectorAll('sub')].map(el => el.textContent), safe: !root.querySelector('img'),
        stable: first === root.innerHTML, preserved: root.textContent.includes('broken^(x, mismatch^{x)') };
      root.remove();return result;
    });
    assert.deepEqual(scripts, { supers: ['−d−1', '-12', 'ij'], subs: ['i+(j)', '123', 'j'], safe: true, stable: true, preserved: true });
    assert.deepEqual(writes, [], 'Interaction checks must not write to the collection');
    assert.deepEqual(errors, []);
    console.log('Dialogs at four sizes, drawer dismissal and focus, outline navigation, reading widths and script notation passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
