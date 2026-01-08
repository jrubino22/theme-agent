const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i === -1) return null;
  return process.argv[i + 1] ?? null;
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function safeName(route) {
  return route.replaceAll("/", "_").replaceAll("?", "_").replaceAll("=", "_").replaceAll("&", "_") || "_root";
}

function loadJson(p) {
  if (!p) return null;
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

async function runAssertions(page, assertions) {
  // assertions format:
  // { "mustHave": [{"selector":"main","minCount":1}, ...],
  //   "textContains": [{"selector":"h1","contains":"Example"}],
  //   "notPresent": [{"selector":".broken"}]
  // }
  let failures = 0;
  if (!assertions) return failures;

  const mustHave = assertions.mustHave || [];
  for (const a of mustHave) {
    const selector = a.selector;
    const minCount = a.minCount ?? 1;
    const count = await page.locator(selector).count();
    if (count < minCount) {
      console.error(`Assertion failed: mustHave ${selector} count=${count} < ${minCount}`);
      failures++;
    }
  }

  const textContains = assertions.textContains || [];
  for (const a of textContains) {
    const selector = a.selector;
    const contains = a.contains || "";
    const txt = await page.locator(selector).first().innerText().catch(() => "");
    if (!txt.includes(contains)) {
      console.error(`Assertion failed: textContains ${selector} missing "${contains}" (got "${txt}")`);
      failures++;
    }
  }

  const notPresent = assertions.notPresent || [];
  for (const a of notPresent) {
    const selector = a.selector;
    const count = await page.locator(selector).count();
    if (count > 0) {
      console.error(`Assertion failed: notPresent ${selector} count=${count}`);
      failures++;
    }
  }

  return failures;
}

function maybeVisualDiff(outDir, pageShotPath, designDir, routeKey) {
  if (!designDir) return { ok: true, summary: "visual diff skipped" };

  const expected = path.join(designDir, `${routeKey}.png`);
  if (!fs.existsSync(expected)) {
    return { ok: true, summary: `visual diff skipped (no design image for ${routeKey})` };
  }

  const diffPath = path.join(outDir, `diff_${routeKey}.png`);
  const reportPath = path.join(outDir, `diff_${routeKey}.json`);

  try {
    const out = execFileSync("node", ["/app/agent/verify/visual_diff.js", expected, pageShotPath, diffPath, reportPath], {
      encoding: "utf-8",
    });
    return { ok: true, summary: out.trim() };
  } catch (e) {
    return { ok: false, summary: `visual diff failed for ${routeKey}: ${String(e.message || e)}` };
  }
}

async function main() {
  const baseUrl = arg("--base-url");
  const outDir = arg("--out-dir") || "./playwright-artifacts";
  const routesRaw = arg("--routes") || "/";
  const assertsPath = arg("--asserts");
  const designDir = arg("--design-dir");

  const routes = routesRaw.split(",").map((r) => r.trim()).filter(Boolean);

  if (!baseUrl) {
    console.error("Missing --base-url");
    process.exit(2);
  }

  ensureDir(outDir);

  const assertions = loadJson(assertsPath);

  const browser = await chromium.launch();
  const page = await browser.newPage();

  let failures = 0;
  let visualFailures = 0;

  for (const route of routes) {
    const url = new URL(route, baseUrl).toString();
    const key = safeName(route);

    console.log(`Visiting: ${url}`);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });

    // baseline assertion: main exists
    const hasMain = await page.locator("main").count();
    if (!hasMain) {
      console.error(`Assertion failed: <main> not found on ${route}`);
      failures++;
    }

    // task-specific assertions if provided
    failures += await runAssertions(page, assertions);

    // screenshot + HTML
    const shotPath = path.join(outDir, `page_${key}.png`);
    await page.screenshot({ path: shotPath, fullPage: true });
    const html = await page.content();
    fs.writeFileSync(path.join(outDir, `page_${key}.html`), html, "utf-8");

    // visual diff if design image exists
    const vd = maybeVisualDiff(outDir, shotPath, designDir, `page_${key}`);
    if (!vd.ok) {
      console.error(vd.summary);
      visualFailures++;
    } else {
      console.log(vd.summary);
    }
  }

  await browser.close();

  if (failures > 0 || visualFailures > 0) process.exit(1);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
