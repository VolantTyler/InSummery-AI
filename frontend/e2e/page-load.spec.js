import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const budgets = JSON.parse(
  readFileSync(join(__dirname, "..", "perf-budgets.json"), "utf8")
).auth;

async function collectPaintMetrics(page) {
  return page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0];
    const paints = performance.getEntriesByType("paint");
    const fp = paints.find((p) => p.name === "first-paint");
    const fcp = paints.find((p) => p.name === "first-contentful-paint");

    let lcp = null;
    try {
      const lcpEntries = performance.getEntriesByType("largest-contentful-paint");
      if (lcpEntries.length) {
        lcp = lcpEntries[lcpEntries.length - 1].startTime;
      }
    } catch {
      // LCP observer entry type may be unavailable.
    }

    return {
      time_to_paint_ms: fp ? fp.startTime : null,
      first_contentful_paint_ms: fcp ? fcp.startTime : null,
      largest_contentful_paint_ms: lcp,
      dom_content_loaded_ms: nav ? nav.domContentLoadedEventEnd : null,
      ttfb_ms: nav ? nav.responseStart : null,
      transfer_size: nav ? nav.transferSize : null,
    };
  });
}

test.describe("auth shell page load", () => {
  test("paints InSummery brand within budget and records metrics", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    // Boot shell or auth view must show the brand (first paint signal).
    await expect(page.getByText("InSummery").first()).toBeVisible({ timeout: 10_000 });

    // Prefer settled auth view when mock auth resolves.
    await page.waitForTimeout(250);
    const metrics = await collectPaintMetrics(page);

    const outDir = join(__dirname, "..", "test-results");
    mkdirSync(outDir, { recursive: true });
    writeFileSync(
      join(outDir, "page-load-metrics.json"),
      JSON.stringify({ capturedAt: new Date().toISOString(), metrics, budgets }, null, 2)
    );

    console.log("page-load metrics:", JSON.stringify(metrics));

    if (metrics.time_to_paint_ms != null) {
      expect(
        metrics.time_to_paint_ms,
        `time_to_paint ${metrics.time_to_paint_ms}ms exceeded budget ${budgets.time_to_paint_ms}ms`
      ).toBeLessThanOrEqual(budgets.time_to_paint_ms);
    }

    if (metrics.first_contentful_paint_ms != null) {
      expect(
        metrics.first_contentful_paint_ms,
        `FCP ${metrics.first_contentful_paint_ms}ms exceeded budget ${budgets.first_contentful_paint_ms}ms`
      ).toBeLessThanOrEqual(budgets.first_contentful_paint_ms);
    }

    if (metrics.largest_contentful_paint_ms != null) {
      expect(
        metrics.largest_contentful_paint_ms,
        `LCP ${metrics.largest_contentful_paint_ms}ms exceeded budget ${budgets.largest_contentful_paint_ms}ms`
      ).toBeLessThanOrEqual(budgets.largest_contentful_paint_ms);
    }

    if (metrics.dom_content_loaded_ms != null) {
      expect(
        metrics.dom_content_loaded_ms,
        `DCL ${metrics.dom_content_loaded_ms}ms exceeded budget ${budgets.dom_content_loaded_ms}ms`
      ).toBeLessThanOrEqual(budgets.dom_content_loaded_ms);
    }

    if (metrics.ttfb_ms != null) {
      expect(
        metrics.ttfb_ms,
        `TTFB ${metrics.ttfb_ms}ms exceeded budget ${budgets.ttfb_ms}ms`
      ).toBeLessThanOrEqual(budgets.ttfb_ms);
    }

    // At least one paint metric must be present so the suite cannot silently pass empty.
    expect(
      metrics.time_to_paint_ms != null || metrics.first_contentful_paint_ms != null
    ).toBeTruthy();
  });

  test("auth view is code-split (firebase/react vendor chunks present)", async ({ page }) => {
    const jsRequests = [];
    page.on("request", (req) => {
      if (req.resourceType() === "script") {
        jsRequests.push(req.url());
      }
    });

    await page.goto("/", { waitUntil: "networkidle" });
    await expect(page.getByText("InSummery").first()).toBeVisible();

    const joined = jsRequests.join("\n");
    // Vite hashed chunk names include the manualChunks keys.
    expect(joined).toMatch(/react-vendor|firebase/);
  });
});
