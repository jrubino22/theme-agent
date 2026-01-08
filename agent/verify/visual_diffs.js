const fs = require("fs");
const pixelmatch = require("pixelmatch");
const { PNG } = require("pngjs");

function readPng(p) {
  return PNG.sync.read(fs.readFileSync(p));
}

function writePng(p, png) {
  fs.writeFileSync(p, PNG.sync.write(png));
}

function main() {
  const [expectedPath, actualPath, diffPath, reportPath] = process.argv.slice(2);
  if (!expectedPath || !actualPath || !diffPath || !reportPath) {
    console.error("Usage: node visual_diff.js expected.png actual.png diff.png report.json");
    process.exit(2);
  }

  const img1 = readPng(expectedPath);
  const img2 = readPng(actualPath);

  // If sizes differ, fail clearly
  if (img1.width !== img2.width || img1.height !== img2.height) {
    const report = {
      ok: false,
      reason: "size_mismatch",
      expected: { width: img1.width, height: img1.height },
      actual: { width: img2.width, height: img2.height },
    };
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf-8");
    console.log(`visual diff: size mismatch`);
    process.exit(1);
  }

  const diff = new PNG({ width: img1.width, height: img1.height });
  const mismatched = pixelmatch(img1.data, img2.data, diff.data, img1.width, img1.height, { threshold: 0.1 });

  writePng(diffPath, diff);

  const total = img1.width * img1.height;
  const ratio = total ? mismatched / total : 0;

  const report = {
    ok: true,
    mismatchedPixels: mismatched,
    totalPixels: total,
    mismatchRatio: ratio,
  };

  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf-8");
  console.log(`visual diff: mismatchRatio=${ratio.toFixed(6)} mismatched=${mismatched}`);
  process.exit(0);
}

main();
