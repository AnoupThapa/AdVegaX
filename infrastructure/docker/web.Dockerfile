# AdVegaX web application (Next.js standalone output). Multi-stage, runs as a non-root user.
# The API address is public and fixed at build time (it is compiled into the browser code):
#   docker build -f infrastructure/docker/web.Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com -t advegax-web .
# The build refuses a plain-http address unless it points at localhost (lib/config/public-config.ts).
FROM node:24-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc* ./
RUN npm ci --no-audit --no-fund

FROM node:24-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

FROM node:24-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
# Only the standalone server, its traced dependencies and static assets — no source, no dev tools.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
