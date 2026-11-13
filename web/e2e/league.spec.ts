import { expect, test } from "@playwright/test";

test("scoreboard, sort, member card, and head to head", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "CAPITOL STREET BETS" })).toBeVisible();
  await expect(page.locator("[data-sample=true]")).toContainText("fictional");
  await expect(page.getByText("Data: Alpha Vantage")).toBeVisible();
  await expect(page.getByText(/For entertainment/)).toBeVisible();
  await expect(page.getByText("The only league where everyone files late.")).toBeVisible();
  await expect(page.locator(".hero")).toContainText(/beaten|trailed/);
  await expect(page.getByRole("img", { name: /Indexed performance/ })).toBeVisible();
  await expect(page.locator(".status")).toContainText("enough priced trades to rank");
  await page.getByRole("button", { name: "30 days" }).click();
  await page.waitForSelector("#board[data-settled=true]");
  await expect(page.locator("[data-on-fire=true]").first()).toBeVisible();
  await expect(page.locator("[data-elevator=true]").first()).toBeVisible();
  await expect(page.locator("#confetti")).toHaveAttribute("data-state", "fired");
  await expect(page.locator("#board > a.row").first()).toContainText("Jordan Hale");
  await page.screenshot({ path: "test-results/league-desktop.png", fullPage: true });

  await page.getByRole("button", { name: "Return", exact: true }).click();
  await page.getByRole("button", { name: "Return", exact: true }).click();
  await expect(page.locator("#board > a.row").first()).toContainText("Riley Okonkwo");

  await page.getByRole("button", { name: "6 months" }).click();
  await expect(page.getByRole("button", { name: "6 months" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Copy-trading" }).click();
  await expect(page.getByRole("button", { name: "Copy-trading" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Member's return" }).click();
  await page.getByRole("combobox", { name: "Chamber" }).selectOption("Senate");
  await expect(page.locator("#board > a.row").first()).toContainText("Senate");
  await page.getByRole("combobox", { name: "Chamber" }).selectOption("all");
  await page.getByRole("button", { name: "30 days" }).click();
  await page.waitForSelector("#board[data-settled=true]");

  await page.locator("#board").getByRole("link", { name: /Jordan Hale/ }).click();
  await expect(page.getByRole("heading", { name: "Jordan Hale" })).toBeVisible();
  await expect(page.getByRole("table")).toContainText("Official search");
  await expect(page.getByRole("img", { name: /Indexed member return/ })).toBeVisible();
  await page.screenshot({ path: "test-results/member-desktop.png", fullPage: true });

  await page.getByRole("link", { name: "Head to head" }).click();
  await expect(page.getByText(/You'd rather copy|Too close to call|Neither left/)).toBeVisible();
  await page.screenshot({ path: "test-results/versus-desktop.png", fullPage: true });
});

test("most traded stocks", async ({ page }) => {
  await page.goto("/");
  await page.waitForSelector("#board[data-settled=true]");
  await expect(page.getByRole("region", { name: "Most traded stocks" }).locator("a.stock-card").first()).toBeVisible();
  await page.getByRole("link", { name: "Stocks", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Most traded stocks" })).toBeVisible();
  await expect(page.locator("#stock-NVDA")).toContainText("NVDA");
});

test("filings tab", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Filings/ }).click();
  await expect(page.getByRole("heading", { name: "Filings" })).toBeVisible();
  await expect(page.locator(".filing").nth(1)).toBeVisible();
  await page.getByRole("button", { name: "Sells" }).click();
  await expect(page.locator(".filing:not(.head) .side.buy")).toHaveCount(0);
});

test("mobile league stacks into cards", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.waitForSelector("#board[data-settled=true]");
  await expect(page.locator(".hero")).toBeVisible();
  await expect(page.locator("a.row").first()).toBeVisible();
  await page.screenshot({ path: "test-results/league-mobile.png", fullPage: true });
});
