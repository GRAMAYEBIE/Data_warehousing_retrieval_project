# Web interface of the assistant: built with Node, served by nginx.
FROM node:22.18.0-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# nginx serves the static files and proxies /api to the assistant API, adding the API
# token on the server side: the token is never in the code sent to the browser.
FROM nginx:1.28.0-alpine
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
# 127.0.0.1, not localhost: in this image localhost can resolve to ::1 first, where nginx
# does not listen (observed on macOS: the container was reported unhealthy while serving).
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
