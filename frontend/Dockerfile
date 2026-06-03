# syntax=docker/dockerfile:1.7
# ----------------------------------------------------------------------------
# Multi-stage build for the Next.js frontend (standalone output).
#   deps    -> install node_modules (cached on package*.json)
#   builder -> next build (produces .next/standalone)
#   runner  -> minimal node runtime, non-root
# ----------------------------------------------------------------------------

# ---------- deps ----------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ---------- builder ----------
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* are inlined at build time -> pass as a build arg.
ARG NEXT_PUBLIC_SSO_ENABLED=false
ENV NEXT_PUBLIC_SSO_ENABLED=$NEXT_PUBLIC_SSO_ENABLED
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ---------- runner ----------
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# BACKEND_ORIGIN is read at runtime by next.config rewrites (dev-style proxy);
# harmless in Docker where nginx routes /api directly.
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

# Standalone bundle + static assets + public dir.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

# server.js is emitted by Next's standalone output.
CMD ["node", "server.js"]
