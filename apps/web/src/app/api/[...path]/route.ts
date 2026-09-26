/**
 * Runtime API proxy: /api/* -> ${API_INTERNAL_URL}/api/*.
 *
 * Replaces build-time rewrites (which Next.js bakes into the image) so one
 * image works in every environment. Streams request and response bodies,
 * so Server-Sent Events pass straight through. Only an allowlist of request
 * headers is forwarded; hop-by-hop and encoding headers are dropped.
 *
 * X-Forwarded-For is forwarded only when WEB_TRUST_FORWARDED_FOR=true, i.e.
 * when this web tier sits behind a reverse proxy / load balancer that sets
 * it. Otherwise a browser could supply its own value and spoof the client IP
 * recorded in audit logs and used for rate limiting.
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API = (process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

const FORWARD = ["authorization", "content-type", "accept", "x-api-key", "x-tenant-id", "x-request-id", "user-agent", "last-event-id"];
const TRUST_XFF = process.env.WEB_TRUST_FORWARDED_FOR === "true";
const DROP_RESPONSE = new Set(["connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length", "upgrade"]);

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const search = new URL(req.url).search;
  const target = `${API}/api/${path.map(encodeURIComponent).join("/")}${search}`;

  const headers = new Headers();
  for (const name of FORWARD) {
    const v = req.headers.get(name);
    if (v) headers.set(name, v);
  }
  const xff = TRUST_XFF ? req.headers.get("x-forwarded-for") : null;
  if (xff) headers.set("x-forwarded-for", xff);

  const init: RequestInit & { duplex?: "half" } = {
    method: req.method, headers, redirect: "manual", cache: "no-store",
  };
  if (!["GET", "HEAD"].includes(req.method)) {
    init.body = req.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch {
    return Response.json({ error: "upstream_unavailable", message: "The API is unreachable." }, { status: 502 });
  }
  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!DROP_RESPONSE.has(key.toLowerCase())) out.set(key, value);
  });
  if ((upstream.headers.get("content-type") || "").includes("text/event-stream")) {
    out.set("x-accel-buffering", "no");
    out.set("cache-control", "no-cache, no-transform");
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
