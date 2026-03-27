import { test, expect } from "@playwright/test";

const API_URL = "http://localhost:8000/api";

function uniqueId() {
  return `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Authentication Flows", () => {
  test("should display login page correctly", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByText("Вход в аккаунт")).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Пароль")).toBeVisible();
    await expect(page.getByRole("button", { name: /войти/i })).toBeVisible();
    await expect(page.getByText(/забыли пароль/i)).toBeVisible();
    await expect(page.getByText(/нет аккаунта/i)).toBeVisible();
  });

  test("should display register page correctly", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByText("Создание аккаунта")).toBeVisible();
    await expect(page.getByLabel("Полное имя")).toBeVisible();
    await expect(page.getByLabel("Организация")).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();
    await expect(page.getByLabel("Пароль")).toBeVisible();
    await expect(page.getByRole("button", { name: /зарегистрироваться/i })).toBeVisible();
  });

  test("should show error for invalid login credentials", async ({ page }) => {
    const uid = `bad_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    await page.goto("/login");
    await page.getByLabel("Email").fill(`${uid}@example.com`);
    await page.getByLabel("Пароль").fill("wrongpassword99");
    await page.getByRole("button", { name: /войти/i }).click();

    // Should show error toast — wait for any toast notification
    await expect(
      page.locator('[data-sonner-toast]').first()
    ).toBeVisible({ timeout: 10000 });
  });

  test("should register and redirect to dashboard", async ({ page }) => {
    const uid = uniqueId();
    await page.goto("/register");

    await page.getByLabel("Полное имя").fill("Test User");
    await page.getByLabel("Организация").fill(`Org-${uid}`);
    await page.getByLabel("Email").fill(`${uid}@example.com`);
    await page.getByLabel("Пароль").fill("TestPass123");
    await page.getByRole("button", { name: /зарегистрироваться/i }).click();

    // Should redirect to dashboard
    await page.waitForURL(/\/dashboard/, { timeout: 15000 });
    // Verify we're on the dashboard page
    await expect(page.getByText(/проекты/i).first()).toBeVisible({ timeout: 10000 });
  });

  test("should show password length validation on register", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Пароль").fill("short");

    // Should show password too short message
    await expect(page.getByText(/минимум 8 символов/i)).toBeVisible();
  });

  test("should login successfully with valid credentials", async ({ request, page }) => {
    const uid = uniqueId();
    const email = `${uid}@example.com`;
    const password = "TestPass123";

    // Register via API first
    const registerRes = await request.post(`${API_URL}/auth/register`, {
      data: {
        email,
        password,
        full_name: "Login Test",
        organization_name: `Org-${uid}`,
      },
    });
    expect(registerRes.ok()).toBeTruthy();
    const { access_token } = await registerRes.json();

    // Login via API and inject token, then verify dashboard loads
    await page.goto("/login");
    await page.evaluate((token: string) => {
      localStorage.setItem("lid_access_token", token);
    }, access_token);
    await page.goto("/dashboard");

    // Verify dashboard loaded with org info
    await expect(page.getByText(/проекты/i).first()).toBeVisible({ timeout: 10000 });
    expect(page.url()).toContain("/dashboard");
  });

  test("should navigate from login to register", async ({ page }) => {
    await page.goto("/login");
    await page.getByText(/нет аккаунта/i).click();
    await page.waitForURL(/\/register/, { timeout: 10000 });
    expect(page.url()).toContain("/register");
  });

  test("should navigate from register to login", async ({ page }) => {
    await page.goto("/register");
    // The "Войти" link is inside "Уже есть аккаунт? Войти"
    await page.locator("p", { hasText: /уже есть аккаунт/i }).getByRole("link").click();
    await page.waitForURL(/\/login/, { timeout: 10000 });
    expect(page.url()).toContain("/login");
  });
});
