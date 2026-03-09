FROM oven/bun:1.3.10 AS deps
WORKDIR /repo
COPY package.json ./package.json
COPY bun.lock ./bun.lock
COPY apps/web/package.json ./apps/web/package.json
COPY apps/desktop/package.json ./apps/desktop/package.json
COPY packages/app/package.json ./packages/app/package.json
COPY packages/config/package.json ./packages/config/package.json
COPY packages/features/package.json ./packages/features/package.json
COPY packages/lib/package.json ./packages/lib/package.json
COPY packages/types/package.json ./packages/types/package.json
COPY packages/ui/package.json ./packages/ui/package.json
RUN bun install --frozen-lockfile

FROM node:20-bookworm-slim AS builder
WORKDIR /repo
COPY --from=deps /repo /repo
COPY . .
RUN cd apps/web && npm run build

FROM node:20-bookworm-slim AS runtime
WORKDIR /repo/apps/web
ENV NODE_ENV=production
COPY --from=builder /repo/package.json /repo/package.json
COPY --from=builder /repo/node_modules /repo/node_modules
COPY --from=builder /repo/apps/web /repo/apps/web
COPY --from=builder /repo/packages /repo/packages
EXPOSE 3000
CMD ["npm", "run", "start"]
