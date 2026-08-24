# HumanLLM frontend image (multi-stage: build then serve with nginx)
FROM node:22-slim AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

# nginx serves the SPA and proxies /api (REST) and /ws (worker websocket)
# to the backend service. The backend host/port are injected at runtime via
# the BACKEND_HOST / BACKEND_PORT env vars (see docker-compose + entrypoint).
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80
