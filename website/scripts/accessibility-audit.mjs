import { chromium } from "playwright-core";
import path from "node:path";

const baseURL = process.env.A11Y_BASE_URL ?? "http://localhost:8787";
const edgePath = process.env.E2E_BROWSER_PATH ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const axePath = path.resolve("node_modules/axe-core/axe.min.js");
const paths = ["/", "/about", "/programs", "/membership", "/apply", "/contact", "/support", "/volunteer", "/news", "/newsletter"];
const browser = await chromium.launch({ executablePath: edgePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.addInitScript({ path: axePath });
let total = 0;
try {
  for (const route of paths) {
    await page.goto(baseURL + route, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    const result = await page.evaluate(async () => {
      return await axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      });
    });
    total += result.violations.length;
    console.log(`\n${route}: ${result.violations.length} violations`);
    for (const violation of result.violations) {
      console.log(`- ${violation.id} [${violation.impact}] ${violation.help}`);
      for (const node of violation.nodes.slice(0, 4)) {
        console.log(`  ${node.target.join(" ")}`);
      }
    }
  }
  console.log(`\nTOTAL VIOLATIONS: ${total}`);
  if (total > 0) process.exitCode = 1;
} finally {
  await browser.close();
}
