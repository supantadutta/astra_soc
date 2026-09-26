import { test, expect, type Page } from "@playwright/test";

/**
 * End-to-end tests for ASTRASOC. They drive the real UI against a running
 * DEMO-profile backend (see playwright.config.ts): sign-in, the SOC
 * workspace, and the MSSP flows — portfolio, tenant switching with the
 * delegation banner, unified queue and customer onboarding.
 */

const PASSWORD = "Demo!Pass123";

async function login(page: Page, email: string, landing: RegExp) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(landing);
}

const customerLogin = (page: Page) => login(page, "manager@acme.io", /\/dashboard/);
const providerLogin = (page: Page, email = "soc@astrasoc.io") => login(page, email, /\/mssp$/);

test("demo accounts are advertised only because this backend seeded them", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByText("Demo environment · simulated data")).toBeVisible();
});

test("customer SOC manager lands on the tenant dashboard", async ({ page }) => {
  await customerLogin(page);
  await expect(page.getByRole("heading", { name: "SOC Overview" })).toBeVisible();
  await expect(page.getByText("Global Risk")).toBeVisible();
  await expect(page.getByTitle(/DEMO mode/)).toBeVisible();
  // Customer users never see provider portfolio navigation.
  await expect(page.getByRole("link", { name: "Portfolio" })).toHaveCount(0);
});

test("incident workspace: SLA, notes and analyst evidence", async ({ page }) => {
  await customerLogin(page);
  await page.goto("/incidents");
  await page.getByText(/INC-/).first().click();
  await expect(page.getByRole("button", { name: /Run Investigation/ })).toBeVisible();
  await expect(page.getByText("SLA", { exact: true })).toBeVisible();

  const note = `e2e note ${Date.now()}`;
  await page.getByPlaceholder("Add an analyst note…").fill(note);
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("Note added to the timeline.")).toBeVisible();

  await page.getByRole("button", { name: "Evidence & Hypotheses" }).click();
  await page.getByPlaceholder("Title").fill("Analyst: lateral movement ruled out");
  await page.getByRole("button", { name: "Add evidence" }).click();
  await expect(page.getByText("Evidence added.")).toBeVisible();
});

test("run investigation produces agent output", async ({ page }) => {
  await customerLogin(page);
  await page.goto("/incidents");
  await page.getByText(/INC-/).first().click();
  await page.getByRole("button", { name: /Run Investigation/ }).click();
  await expect(page.getByText(/Coordinator workflow executed/)).toBeVisible({ timeout: 30000 });
});

test("MSSP portfolio → open customer → delegation banner → return home", async ({ page }) => {
  await providerLogin(page);
  await expect(page.getByRole("heading", { name: "Managed Service Portfolio" })).toBeVisible();
  await page.getByRole("button", { name: /Acme Corp/ }).first().click();
  await page.waitForURL(/\/dashboard/);
  await expect(page.getByText(/Acting in/)).toBeVisible();
  await expect(page.getByText(/recorded in the customer's audit trail/)).toBeVisible();
  await page.getByRole("button", { name: /Return to/ }).click();
  await expect(page.getByText(/Acting in/)).toHaveCount(0);
});

test("unified queue lists incidents across customers with SLA state", async ({ page }) => {
  await providerLogin(page);
  await page.goto("/mssp/queue");
  await expect(page.getByRole("heading", { name: "Unified Queue" })).toBeVisible();
  const table = page.locator("table");
  await expect(table.getByText(/INC-/).first()).toBeVisible();
  await expect(table.getByText(/Breached|At risk|On track/).first()).toBeVisible();
});

test("granted analyst sees only granted customers in the switcher", async ({ page }) => {
  await login(page, "analyst@astrasoc.io", /\/mssp$|\/dashboard/);
  await page.getByTitle("Switch tenant").click();
  const list = page.getByRole("listbox");
  await expect(list.getByText("Acme Corp")).toBeVisible();
  await expect(list.getByText("Initech")).toHaveCount(0);
});

test("onboard a customer end to end", async ({ page }) => {
  await providerLogin(page, "admin@astrasoc.io");
  await page.goto("/mssp/customers");
  await page.getByRole("button", { name: "Onboard customer" }).click();
  const name = `E2E Customer ${Date.now() % 100000}`;
  await page.getByLabel("Organization name").fill(name);
  await page.getByRole("button", { name: "Onboard", exact: true }).click();
  await expect(page.getByText(name).first()).toBeVisible();
});

test("every module route renders for the platform admin", async ({ page }) => {
  await providerLogin(page, "admin@astrasoc.io");
  for (const path of [
    "/mssp", "/mssp/queue", "/mssp/sla", "/mssp/customers", "/mssp/access", "/mssp/content",
    "/mssp/handover", "/mssp/billing", "/dashboard", "/alerts", "/incidents", "/notifications",
    "/entities", "/attack-paths", "/agents", "/query", "/threat-intel", "/detections", "/playbooks",
    "/knowledge", "/response", "/approvals", "/reports", "/models", "/connectors", "/platform-health",
    "/audit", "/rbac", "/tenants", "/account", "/settings", "/demo",
  ]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await expect(page.locator("h1").first(), path).toBeVisible();
  }
});
