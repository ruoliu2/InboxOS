FROM oven/bun:1.3.10 AS deps
WORKDIR /repo/apps/web
COPY apps/web/package.json ./package.json
COPY apps/web/bun.lock ./bun.lock
RUN bun install --frozen-lockfile

FROM node:20-bookworm-slim AS builder
WORKDIR /repo/apps/web
COPY --from=deps /repo/apps/web/node_modules ./node_modules
COPY apps/web ./
COPY packages /repo/packages
RUN npm run build

FROM node:20-bookworm-slim AS runtime
WORKDIR /repo/apps/web
ENV NODE_ENV=production
COPY --from=builder /repo/apps/web /repo/apps/web
EXPOSE 3000
CMD ["npm", "run", "start"]
