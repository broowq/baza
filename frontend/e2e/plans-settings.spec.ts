import { test, expect } from "@playwright/test";

const API_URL = "http://localhost:8000/api";

function uniqueId() {
  return `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

async function createTestUser(request: any) {
  const uid = uniqueId();
  const email = `${uid}@example.com`;
  const password = "TestPass123";
  const orgName = `Org-${uid}`;

  const registerRes = await request.post(`${API_URL}/auth/register`, {
    data: { email, password, full_name: "E2E Tester", organization_name: orgName },
  });
  expect(registerRes.ok()).toBeTruthy();
  const { access_token } = await registerRes.json();

  const orgsRes = await request.get(`${API_URL}/organizations/my-list`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  expect(orgsRes.ok()).toBeTruthy();
  const orgs = await orgsRes.json();

  return { email, password, accessToken: access_token, orgId: orgs[0].id, orgName };
}

async function loginViaUI(page: any, email: string, password: string, accessToken?: string) {
  if (accessToken) {
    await page.goto("/login");
    await page.evaluate((token: string) => {
      localStorage.setItem("lid_access_token", token);
    }, accessToken);
    await page.goto("/dashboard");
    return;
  }
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: /войти/i }).click();
  await page.waitForURL(/\/dashboard/, { timeout: 15000 });
}

test.describe("Plans Page", () => {
  test("should display all 3 plan cards", async ({ page }) => {
    await page.goto("/plans");
    await expect(page.getByRole("button", { name: /текущий тариф/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /перейти на pro/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /перейти на team/i })).toBeVisible();
  });

  test("should display pricing info", async ({ page }) => {
    await page.goto("/plans");
    await expect(page.getByRole("button", { name: /текущий тариф/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/лидов\/мес/).first()).toBeVisible();
    await expect(page.getByText(/проектов/).first()).toBeVisible();
  });

  test("should display page heading", async ({ page }) => {
    await page.goto("/plans");
    await expect(page.getByText("Выберите тариф под ваш рост")).toBeVisible();
    await expect(page.getByText("платите только за то, что используете")).toBeVisible();
  });

  test("should highlight Pro plan as popular", async ({ page }) => {
    await page.goto("/plans");
    await expect(page.getByText("Популярный")).toBeVisible({ timeout: 10000 });
  });

  test("should have select buttons for each plan", async ({ page }) => {
    await page.goto("/plans");
    await expect(page.getByRole("button", { name: /текущий тариф/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /перейти на pro/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /перейти на team/i })).toBeVisible();
  });
});

test.describe("Settings Page", () => {
  let email: string;
  let password: string;

  test.beforeEach(async ({ request, page }) => {
    const user = await createTestUser(request);
    email = user.email;
    password = user.password;
    await loginViaUI(page, email, password, user.accessToken);
  });

  test("should display profile section", async ({ page }) => {
    await page.goto("/dashboard/settings");
    // Profile tab is active by default
    await expect(page.getByText("Профиль пользователя")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(email).first()).toBeVisible();
  });

  test("should display org settings", async ({ page }) => {
    await page.goto("/dashboard/settings");
    // Click the "Организация" tab to see org settings
    await page.getByRole("tab", { name: /организация/i }).click();
    await expect(page.getByText(/тариф/i).first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/лиды/i).first()).toBeVisible();
  });

  test("should display members section", async ({ page }) => {
    await page.goto("/dashboard/settings");
    // Click the "Участники" tab
    await page.getByRole("tab", { name: /участники/i }).click();
    await expect(page.getByText("Участники").first()).toBeVisible({ timeout: 10000 });
  });

  test("should display activity log section", async ({ page }) => {
    await page.goto("/dashboard/settings");
    // Click the "Журнал" tab
    await page.getByRole("tab", { name: /журнал/i }).click();
    await expect(page.getByText("Журнал действий")).toBeVisible({ timeout: 10000 });
  });

  test("should display invitations section", async ({ page }) => {
    await page.goto("/dashboard/settings");
    // Click the "Приглашения" tab
    await page.getByRole("tab", { name: /приглашения/i }).click();
    await expect(page.getByText("Приглашения").first()).toBeVisible({ timeout: 10000 });
  });

  test("should have change password form", async ({ page }) => {
    await page.goto("/dashboard/settings");
    // Profile tab is default and contains the password form
    await expect(page.getByLabel("Текущий пароль")).toBeVisible({ timeout: 10000 });
    await expect(page.getByLabel("Новый пароль")).toBeVisible();
    await expect(page.getByRole("button", { name: /Сменить пароль/i })).toBeVisible();
  });

  test("should have link to plans page", async ({ page }) => {
    await page.goto("/dashboard/settings");
    // "Открыть тарифы" button is in the "Организация" tab
    await page.getByRole("tab", { name: /организация/i }).click();
    await expect(page.getByRole("button", { name: /Открыть тарифы/i })).toBeVisible({ timeout: 10000 });
  });
});
