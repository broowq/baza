import { test, expect } from "@playwright/test";

const API_URL = "http://localhost:8000/api";

/**
 * Helper: register a new user via API and return credentials + org ID.
 */
async function createTestUser(request: any) {
  const unique = `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const email = `${unique}@example.com`;
  const password = "TestPass123";
  const fullName = "E2E Tester";
  const orgName = `Org-${unique}`;

  const registerRes = await request.post(`${API_URL}/auth/register`, {
    data: { email, password, full_name: fullName, organization_name: orgName },
  });
  expect(registerRes.ok()).toBeTruthy();
  const { access_token } = await registerRes.json();

  const orgsRes = await request.get(`${API_URL}/organizations/my-list`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  expect(orgsRes.ok()).toBeTruthy();
  const orgs = await orgsRes.json();

  return { email, password, accessToken: access_token, orgId: orgs[0].id };
}

/**
 * Helper: login via the UI and navigate to dashboard.
 */
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

test.describe("Project Creation", () => {
  let email: string;
  let password: string;
  let orgId: string;
  let accessToken: string;

  test.beforeEach(async ({ request, page }) => {
    const user = await createTestUser(request);
    email = user.email;
    password = user.password;
    orgId = user.orgId;
    accessToken = user.accessToken;
    await loginViaUI(page, email, password, accessToken);
  });

  test("should show and hide the project creation form", async ({ page }) => {
    // Dialog form should not be visible initially
    await expect(page.getByLabel("Название проекта")).not.toBeVisible();

    // Open dialog
    await page.getByRole("button", { name: /создать проект|новый проект/i }).click();
    await expect(page.getByLabel("Название проекта")).toBeVisible();

    // Close dialog via "Отмена"
    await page.getByRole("button", { name: "Отмена" }).click();
    await expect(page.getByLabel("Название проекта")).not.toBeVisible();
  });

  test("should create a project successfully", async ({ page }) => {
    await page.getByRole("button", { name: /создать проект|новый проект/i }).click();

    await page.getByLabel("Название проекта").fill("Тестовый проект E2E");
    await page.getByLabel("Ниша").fill("деревообработка");
    await page.getByLabel("Регион или город").fill("Москва");
    await page.getByLabel("Сегменты").fill("пиломатериалы, фанера");

    await page.getByRole("button", { name: /создать проект/i }).click();

    // Verify toast
    await expect(page.getByText("Проект создан")).toBeVisible({ timeout: 10000 });

    // Verify project card
    await expect(page.getByText("Тестовый проект E2E")).toBeVisible();
    await expect(page.getByText("деревообработка")).toBeVisible();
    await expect(page.getByText("Москва")).toBeVisible();

    // Dialog should be hidden after creation
    await expect(page.getByLabel("Название проекта")).not.toBeVisible();
  });

  test("should enforce HTML5 required field validation", async ({ page }) => {
    await page.getByRole("button", { name: /создать проект|новый проект/i }).click();

    // Click submit without filling anything
    await page.getByRole("button", { name: /создать проект/i }).click();

    // Dialog form should remain visible (HTML5 validation blocks submission)
    await expect(page.getByLabel("Название проекта")).toBeVisible();
    // No toast should appear
    await expect(page.getByText("Проект создан")).not.toBeVisible();
  });

  test("should have correct project details link after creation", async ({ page }) => {
    // Create project
    await page.getByRole("button", { name: /создать проект|новый проект/i }).click();
    await page.getByLabel("Название проекта").fill("Детали проект");
    await page.getByLabel("Ниша").fill("IT");
    await page.getByLabel("Регион или город").fill("Казань");
    await page.getByRole("button", { name: /создать проект/i }).click();
    await expect(page.getByText("Проект создан")).toBeVisible({ timeout: 10000 });

    // Project card is a clickable link with correct href
    await page.getByText("Детали проект").waitFor({ timeout: 5000 });
    const projectLink = page.getByRole("link", { name: /детали проект/i }).first();
    await expect(projectLink).toBeVisible();

    const href = await projectLink.getAttribute("href");
    expect(href).toBeTruthy();
    expect(href).toMatch(/\/dashboard\/projects\/[0-9a-f-]+/);
  });

  test("should delete a project via API", async ({ page, request }) => {
    // Create project via API
    const token = await page.evaluate(() => localStorage.getItem("lid_access_token"));
    const orgsRes = await request.get(`${API_URL}/organizations/my-list`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const orgs = await orgsRes.json();
    const orgId = orgs[0].id;

    const projRes = await request.post(`${API_URL}/projects`, {
      headers: { Authorization: `Bearer ${token}`, "X-Org-Id": orgId },
      data: { name: "Удаляемый проект", niche: "тест", geography: "Тест", segments: [] },
    });
    const proj = await projRes.json();

    // Delete via API
    const delRes = await request.delete(`${API_URL}/projects/${proj.id}`, {
      headers: { Authorization: `Bearer ${token}`, "X-Org-Id": orgId },
    });
    expect(delRes.ok()).toBeTruthy();
  });

  test("should show project count in org stats", async ({ page }) => {
    // Initially should show "0 из" in the projects section
    await expect(page.getByText(/0 из/)).toBeVisible();

    // Create a project via dialog
    await page.getByRole("button", { name: /создать проект|новый проект/i }).click();
    await page.getByLabel("Название проекта").fill("Счётчик проект");
    await page.getByLabel("Ниша").fill("тест");
    await page.getByLabel("Регион или город").fill("Тест");
    await page.getByRole("button", { name: /создать проект/i }).click();
    await expect(page.getByText("Проект создан")).toBeVisible({ timeout: 10000 });

    // Counter should update to "1 из"
    await expect(page.getByText(/1 из/)).toBeVisible({ timeout: 5000 });
  });
});
