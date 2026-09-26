# ASTRASOC web image (Next.js standalone output)
#
# The API location is read at RUNTIME by the /api/* proxy route
# (API_INTERNAL_URL, e.g. http://api:8000), so one image works in every
# environment — nothing about the backend is baked in at build time.
FROM node:20-slim AS builder
WORKDIR /app
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts || npm install --ignore-scripts
COPY . .
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN groupadd -g 1001 nodejs && useradd -u 1001 -g nodejs -M nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER 1001:1001
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
