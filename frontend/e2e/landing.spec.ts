import { test, expect } from "@playwright/test";

test.describe("Landing Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("should display hero section", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(/находите клиентов/i)).toBeVisible();
  });

  test("should display stats bar", async ({ page }) => {
    // Stats are below the fold, scroll down
    await page.evaluate(() => window.scrollBy(0, 1200));
    await expect(page.getByText("50 000+").first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("221 город").first()).toBeVisible();
  });

  test("should display features section", async ({ page }) => {
    await page.evaluate(() => window.scrollBy(0, 2000));
    await expect(page.getByRole("heading", { name: "Умный поиск лидов" })).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole("heading", { name: "Обогащение контактов" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Скоринг 0-100" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Экспорт в CSV" })).toBeVisible();
  });

  test("should display how it works section", async ({ page }) => {
    await page.evaluate(() => window.scrollBy(0, 4000));
    await expect(page.getByText("Настройте проект")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Запустите сбор")).toBeVisible();
    await expect(page.getByText("Обогатите данные")).toBeVisible();
    await expect(page.getByText("Экспортируйте")).toBeVisible();
  });

  test("should display pricing section with 3 plans", async ({ page }) => {
    await page.evaluate(() => document.querySelector("#pricing")?.scrollIntoView());
    await expect(page.getByText("Starter").first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("2 900 ₽")).toBeVisible();
    await expect(page.getByText("7 900 ₽")).toBeVisible();
  });

  test("should display FAQ section", async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight - 1500));
    await expect(page.getByText("Вопросы и ответы")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Как происходит сбор лидов?")).toBeVisible();
  });

  test("should expand FAQ accordion", async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight - 1500));
    const faqQuestion = page.getByText("Как происходит сбор лидов?").first();
    await faqQuestion.waitFor({ timeout: 5000 });
    await faqQuestion.click();
    await expect(page.getByText(/SearXNG/).first()).toBeVisible({ timeout: 5000 });
  });

  test("should display footer", async ({ page }) => {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(page.getByText("2026 БАЗА")).toBeVisible({ timeout: 5000 });
  });

  test("should have CTA buttons in hero", async ({ page }) => {
    await expect(page.getByRole("link", { name: /попробовать бесплатно/i }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: /посмотреть тарифы/i }).first()).toBeVisible();
  });

  test("should scroll to pricing section via anchor link", async ({ page }) => {
    await page.getByRole("link", { name: /посмотреть тарифы/i }).first().click();
    // After clicking, the pricing section should be scrolled into view
    await expect(page.getByText("Starter").first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("2 900 ₽")).toBeVisible();
  });

  test("should be responsive on mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });
});
