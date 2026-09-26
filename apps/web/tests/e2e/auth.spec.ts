import { test, expect, request as apiRequest, type Page } from "@playwright/test";
import { createHmac, randomBytes } from "crypto";

/**
 * Browser session security and two-step verification, end to end:
 * tokens never reach page JavaScript, and a user can enroll an authenticator,
 * sign out, and sign back in with a code.
 */

function base32Decode(s: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of s.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

function totp(secret: string, at = Date.now() / 1000): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30)));
  const mac = createHmac("sha1", base32Decode(secret)).update(counter).digest();
  const offset = mac[mac.length - 1] & 0x0f;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function signIn(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("session tokens are not readable by page JavaScript", async ({ page }) => {
  await signIn(page, "manager@acme.io", "Demo!Pass123");
  await page.waitForURL(/\/dashboard/);
  const visible = await page.evaluate(() => ({
    cookies: document.cookie,
    storage: Object.keys(localStorage).join(","),
  }));
  expect(visible.cookies).toContain("astrasoc_csrf");
  expect(visible.cookies).not.toContain("astrasoc_at");
  expect(visible.cookies).not.toContain("astrasoc_rt");
  expect(visible.storage).not.toMatch(/access|refresh|token/i);
});

test("an expired access cookie is refreshed transparently", async ({ page }) => {
  await signIn(page, "manager@acme.io", "Demo!Pass123");
  await page.waitForURL(/\/dashboard/);
  const refreshes: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/v1/auth/refresh")) refreshes.push(r.url());
  });
  // Simulate the one-hour access cookie expiring; the refresh cookie remains.
  // Background polling or the navigation below triggers the refresh; the
  // navigation may abort an in-flight one, which must not end the session.
  await page.context().clearCookies({ name: "astrasoc_at" });
  await page.goto("/incidents");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  // Still signed in on the next navigation (the session was not revoked).
  await page.goto("/alerts");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect(page.url()).toContain("/alerts");
  expect(refreshes.length).toBeGreaterThan(0);
  expect((await page.context().cookies()).map((c) => c.name)).toContain("astrasoc_at");
});

test("enroll two-step verification, sign out, sign back in with a code", async ({ page, baseURL }) => {
  // Provision a fresh account through the API as the platform admin.
  const api = await apiRequest.newContext({ baseURL });
  const adminLogin = await api.post("/api/v1/auth/login", { data: { email: "admin@astrasoc.io", password: "Demo!Pass123" } });
  const { access_token } = await adminLogin.json();
  const email = `e2e-mfa-${randomBytes(3).toString("hex")}@corp.local`;
  const password = "E2e!Mfa-Pass-2026";
  const created = await api.post("/api/v1/rbac/users", {
    headers: { Authorization: `Bearer ${access_token}` },
    data: { email, full_name: "E2E MFA", password, roles: ["auditor"] },
  });
  expect(created.ok()).toBeTruthy();

  await signIn(page, email, password);
  await page.waitForURL(/\/mssp|\/dashboard/);
  await page.goto("/account");
  await page.getByRole("button", { name: "Set up" }).click();
  await expect(page.getByAltText("Authenticator QR code")).toBeVisible();
  const secret = (await page.locator("code").first().innerText()).replace(/\s/g, "");
  await page.getByLabel("Code from the app").fill(totp(secret));
  await page.getByRole("button", { name: /Verify and enable/ }).click();
  await expect(page.getByText(/Save these recovery codes/)).toBeVisible();
  await page.getByRole("button", { name: "I have saved these codes" }).click();
  await expect(page.getByText(/recovery codes left/)).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
  await signIn(page, email, password);
  await expect(page.getByText("Two-step verification")).toBeVisible();
  // The enrollment code's time step is consumed; use the next one.
  await page.getByLabel(/6-digit code/).fill(totp(secret, Date.now() / 1000 + 30));
  await page.getByRole("button", { name: "Verify" }).click();
  await page.waitForURL(/\/mssp|\/dashboard/);
});

for (const [email, landing] of [["manager@acme.io", /\/dashboard/], ["soc@astrasoc.io", /\/mssp/]] as const) {
  test(`header controls stay on screen (${email})`, async ({ page }) => {
    await signIn(page, email, "Demo!Pass123");
    await page.waitForURL(landing);
    const width = page.viewportSize()!.width;
    for (const name of ["Sign out", /Notifications/]) {
      const box = await page.getByRole("button", { name }).boundingBox();
      expect(box, String(name)).not.toBeNull();
      expect(box!.x + box!.width, String(name)).toBeLessThanOrEqual(width);
    }
  });
}
