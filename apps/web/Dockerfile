FROM oven/bun:1.3.5 AS deps
WORKDIR /repo/apps/web
COPY apps/web/package.json apps/web/bun.lock ./
RUN bun install --frozen-lockfile || bun install

FROM oven/bun:1.3.5 AS builder
WORKDIR /repo
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY apps/web ./apps/web
COPY packages ./packages
RUN cd apps/web && bun run build

FROM oven/bun:1.3.5 AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /repo/apps/web/.next ./.next
COPY --from=builder /repo/apps/web/public ./public
COPY --from=builder /repo/apps/web/package.json ./package.json
COPY --from=builder /repo/apps/web/next.config.mjs ./next.config.mjs
COPY --from=builder /repo/apps/web/node_modules ./node_modules
EXPOSE 3000
CMD ["bun", "run", "start"]
