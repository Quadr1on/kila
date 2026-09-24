# KILA web. `next build` produces a standalone server; no CDN, no telemetry, local fonts.
FROM node:24-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Rewrites (/api -> FastAPI) are resolved at build time.
ARG KILA_API_URL=http://api:8000
ENV KILA_API_URL=$KILA_API_URL
RUN npm run build

FROM node:24-slim AS run
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 HOSTNAME=0.0.0.0 PORT=3000
WORKDIR /app
COPY --from=build --chown=node /app/.next/standalone ./
COPY --from=build --chown=node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
