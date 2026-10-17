// Offline browser QA. NODE_PATH may point at the bundled Playwright runtime.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const [source, output] = process.argv.slice(2);
  if (!source || !output) throw new Error('Usage: report_visual_qa.cjs report.html NEW_OUTPUT_DIRECTORY');
  fs.mkdirSync(output); // Refuse overwriting existing QA evidence.
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const evidence = [];
  try {
    for (const width of [1440, 1280, 768, 390]) {
      const page = await browser.newPage({viewport: {width, height: 900}});
      const errors = [], external = [];
      page.on('pageerror', error => errors.push(String(error)));
      page.on('request', request => { if (/^https?:/.test(request.url())) external.push(request.url()); });
      await page.goto(pathToFileURL(path.resolve(source)).href);
      await page.screenshot({path: path.join(output, `report-${width}.png`)});
      const state = await page.evaluate(() => ({
        title: document.title, pageOverflow: document.documentElement.scrollWidth > window.innerWidth,
        sections: [...document.querySelectorAll('section h2')].map(el => el.textContent),
        tables: document.querySelectorAll('table').length,
        brokenAnchors: [...document.querySelectorAll('a[href^="#"]')].filter(a => !document.getElementById(a.hash.slice(1))).length,
        nativeDisclosures: document.querySelectorAll('details').length,
      }));
      if (state.pageOverflow || state.brokenAnchors || errors.length || external.length || state.sections.length !== 8) {
        throw new Error(JSON.stringify({width, ...state, errors, external}));
      }
      // Check long, expanded audit data without horizontal page spill.
      await page.locator('section#audit summary').first().click();
      if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error('Expanded audit overflow');
      await page.locator('#overlap').scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(output, `overlap-${width}.png`)});
      evidence.push({width, ...state, errors, external});
      await page.close();
    }
    fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify(evidence, null, 2), {flag: 'wx'});
    console.log(JSON.stringify(evidence));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
