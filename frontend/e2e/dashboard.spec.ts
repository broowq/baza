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

test.describe("Dashboard", () => {
  let email: string;
  let password: string;
  let orgId: string;

  test.beforeEach(async ({ request, page }) => {
    const user = await createTestUser(request);
    email = user.email;
    password = user.password;
    orgId = user.orgId;
    await loginViaUI(page, email, password, user.accessToken);
  });

  test("should display dashboard with org info", async ({ page }) => {
    // Plan badge shows "Starter", role badge shows "Владелец"
    await expect(page.getByText("Starter").first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Владелец").first()).toBeVisible();
    await expect(page.getByText(/проекты/i).first()).toBeVisible();
  });

  test("should show empty state when no projects", async ({ page }) => {
    await expect(page.getByText(/нет проектов/i)).toBeVisible();
  });

  test("should show lead quota information", async ({ page }) => {
    // Compact quota shows leads count and percentage
    await expect(page.getByText(/\/ 1000/)).toBeVisible();
    await expect(page.getByText("0%")).toBeVisible();
  });

  test("should create and display a project", async ({ page }) => {
    await page.getByRole("button", { name: /создать проект|новый проект/i }).click();
    // Wait for dialog to appear
    await expect(page.getByLabel("Название проекта")).toBeVisible();

    await page.getByLabel("Название проекта").fill("Тестовый проект");
    await page.getByLabel("Ниша").fill("IT-услуги");
    await page.getByLabel("Регион или город").fill("Москва");
    await page.getByLabel("Сегменты").fill("разработка, тестирование");
    await page.getByRole("button", { name: /создать проект/i }).click();

    await expect(page.getByText("Проект создан")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Тестовый проект")).toBeVisible();
    await expect(page.getByText("IT-услуги")).toBeVisible();
  });

  test("should navigate to project details by clicking card", async ({ page }) => {
    await page.getByRole("button", { name: /создать проект|новый проект/i }).click();
    await page.getByLabel("Название проекта").fill("Навигация проект");
    await page.getByLabel("Ниша").fill("строительство");
    await page.getByLabel("Регион или город").fill("СПб");
    await page.getByRole("button", { name: /создать проект/i }).click();
    await expect(page.getByText("Проект создан")).toBeVisible({ timeout: 10000 });

    // Click the project card link
    const projectLink = page.getByRole("link", { name: /навигация проект/i }).first();
    await projectLink.click();
    await page.waitForURL(/\/dashboard\/projects\//, { timeout: 10000 });
    expect(page.url()).toContain("/dashboard/projects/");
  });
});

test.describe("Project Details Page", () => {
  let email: string;
  let password: string;
  let accessToken: string;
  let orgId: string;
  let projectId: string;

  test.beforeEach(async ({ request, page }) => {
    const user = await createTestUser(request);
    email = user.email;
    password = user.password;
    accessToken = user.accessToken;
    orgId = user.orgId;

    const projRes = await request.post(`${API_URL}/projects`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Org-Id": orgId,
      },
      data: {
        name: "Detail Test Project",
        niche: "деревообработка",
        geography: "Казань",
        segments: ["пиломатериалы"],
      },
    });
    expect(projRes.ok()).toBeTruthy();
    const proj = await projRes.json();
    projectId = proj.id;

    await loginViaUI(page, email, password, accessToken);
  });

  test("should display project details", async ({ page }) => {
    await page.goto(`/dashboard/projects/${projectId}`);
    await expect(page.getByText("Detail Test Project")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("деревообработка")).toBeVisible();
    await expect(page.getByText("Казань")).toBeVisible();
  });

  test("should show stat cards", async ({ page }) => {
    await page.goto(`/dashboard/projects/${projectId}`);
    await expect(page.getByText(/всего лидов/i).first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/обогащено/i).first()).toBeVisible();
    await expect(page.getByText(/с email/i).first()).toBeVisible();
    await expect(page.getByText(/средний score/i).first()).toBeVisible();
  });

  test("should show leads table section", async ({ page }) => {
    await page.goto(`/dashboard/projects/${projectId}`);
    // The leads tab is active by default in the Tabs component
    await expect(page.getByRole("tab", { name: /лиды/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByLabel(/поиск по лидам/i)).toBeVisible();
  });

  test("should show filter controls", async ({ page }) => {
    await page.goto(`/dashboard/projects/${projectId}`);
    await expect(page.getByLabel(/фильтр по статусу/i)).toBeVisible({ timeout: 10000 });
    await expect(page.getByLabel(/сортировка/i)).toBeVisible();
    await expect(page.getByLabel(/порядок сортировки/i)).toBeVisible();
  });

  test("should show job history section", async ({ page }) => {
    await page.goto(`/dashboard/projects/${projectId}`);
    // Job history is in a tab — click it to see
    await page.getByRole("tab", { name: /история задач/i }).click();
    await expect(page.getByText(/статус сбора и обогащения/i).first()).toBeVisible({ timeout: 10000 });
  });

  test("should have back navigation link", async ({ page }) => {
    await page.goto(`/dashboard/projects/${projectId}`);
    const backLink = page.getByRole("link", { name: /назад/i });
    await expect(backLink).toBeVisible({ timeout: 10000 });
    await backLink.click();
    await page.waitForURL(/\/dashboard/, { timeout: 10000 });
  });

  test("should have collect and enrich buttons", async ({ page }) => {
    await page.goto(`/dashboard/projects/${projectId}`);
    await expect(page.getByRole("button", { name: /100/i })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /обогатить/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /csv/i })).toBeVisible();
  });
});
