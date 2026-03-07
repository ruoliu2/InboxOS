FROM node:20-bookworm-slim AS builder
WORKDIR /repo
COPY . .
RUN npm install
RUN cd apps/web && npm run build

FROM node:20-bookworm-slim AS runtime
WORKDIR /repo
ENV NODE_ENV=production
COPY --from=builder /repo /repo
WORKDIR /repo/apps/web
EXPOSE 3000
CMD ["npm", "run", "start"]
