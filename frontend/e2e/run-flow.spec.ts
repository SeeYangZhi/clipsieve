import { expect, test } from "@playwright/test";

const PLAN_URL = /\/runs\/[^/]+\/plan$/;
const RUN_URL = /\/runs\/[^/]+$/;
const REPORT_URL = /\/report$/;
const CITE_NAME = /^local:fx-/;
const ALL_PLAYED = /5 \/ 5/;

test("brief -> plan -> live run -> report -> replay", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("Brief")
    .fill(
      "我是一个要搬到上海的新加坡人，想做 vlog，分析这类视频的开头和风格。"
    );
  await page.getByLabel("local", { exact: true }).check();
  await page.getByRole("button", { name: "Start research" }).click();

  await expect(page).toHaveURL(PLAN_URL);
  await expect(
    page.getByRole("button", { name: "Approve and run" })
  ).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Approve and run" }).click();

  await expect(page).toHaveURL(RUN_URL);
  await expect(page.getByText("Done", { exact: true })).toBeVisible({
    timeout: 60_000,
  });
  const collected = page
    .getByText("Collected")
    .locator("xpath=following-sibling::*[1]");
  await expect(collected).toHaveText("5");
  await expect(page.getByTitle("新加坡人在上海的第一周")).toBeVisible();
  await expect(
    page.locator("[data-state='shortlisted']").first()
  ).toBeVisible();

  await page.getByRole("link", { name: "View report" }).click();
  await expect(page).toHaveURL(REPORT_URL);
  await expect(page.getByText("Patterns")).toBeVisible();
  const cite = page.getByRole("button", { name: CITE_NAME }).first();
  await cite.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto(page.url().replace(REPORT_URL, "/replay"));
  await page.getByRole("button", { name: "16x" }).click();
  await expect(page.locator("li[data-testid^='tile-']")).toHaveCount(5, {
    timeout: 30_000,
  });
  await expect(page.getByText(ALL_PLAYED)).toBeVisible();
});
