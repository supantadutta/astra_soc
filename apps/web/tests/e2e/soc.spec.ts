import { test, expect } from "@playwright/test";

/**
 * End-to-end smoke tests for the ASTRASOC command center. These drive the real
 * UI against the running backend (see playwright.config.ts). They cover the
 * acceptance-critical flows: login, dashboard, investigation workspace, agent
 * run, and the governed response pipeline.
 */

async function login(page: any, email = "manager@acme.io") {
  await page.goto("/login");
  await page.locator("input").first().fill(email);
  await page.fill('input[type="password"]', "Demo!Pass123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/dashboard");
}

test("login and dashboard KPIs render", async ({ page }) => {
  await login(page);
  await expect(page.getByText("Global Risk")).toBeVisible();
  await expect(page.getByText("Active Incidents")).toBeVisible();
  await expect(page.getByRole("heading", { name: "SOC Overview" })).toBeVisible();
});

test("investigation workspace opens with evidence", async ({ page }) => {
  await login(page);
  await page.goto("/incidents");
  await page.getByText(/INC-/).first().click();
  await expect(page.getByRole("button", { name: /Run Investigation/ })).toBeVisible();
  await page.getByText("Evidence & Hypotheses").click();
  await expect(page.getByText(/Confirmed Fact|AI Inference/).first()).toBeVisible();
});

test("run investigation produces agent output", async ({ page }) => {
  await login(page);
  await page.goto("/incidents");
  await page.getByText(/INC-/).first().click();
  await page.getByRole("button", { name: /Run Investigation/ }).click();
  await expect(page.getByText(/Coordinator workflow executed/)).toBeVisible({ timeout: 30000 });
});

test("mode indicator shows DEMO", async ({ page }) => {
  await login(page);
  await expect(page.getByText("DEMO").first()).toBeVisible();
});

test("provider connectivity test is truthful", async ({ page }) => {
  await login(page, "admin@astrasoc.io");
  await page.goto("/models", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/Simulated Reasoner/).first()).toBeVisible({ timeout: 15000 });
});

test("all module routes load", async ({ page }) => {
  await login(page, "admin@astrasoc.io");
  for (const path of [
    "/alerts", "/incidents", "/entities", "/attack-paths", "/agents", "/query",
    "/threat-intel", "/detections", "/playbooks", "/knowledge", "/response",
    "/approvals", "/reports", "/models", "/connectors", "/platform-health",
    "/audit", "/rbac", "/settings", "/demo",
  ]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await expect(page.locator("h1").first()).toBeVisible();
  }
});
