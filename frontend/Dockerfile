# =============================================================================
# Storm Energy RTU - web frontend image
#   stage 1 (build) : node, `npm ci` from package-lock.json, `vite build`
#   stage 2 (serve) : nginx-unprivileged (non-root, port 8080) serving dist/ only
# The image contains static files only: no secrets, no API address (the app calls
# same-origin /api, routed by the reverse-proxy service), no source maps.
# =============================================================================
ARG NODE_IMAGE_TAG=22-alpine
ARG NGINX_IMAGE_TAG=1.28-alpine

FROM node:${NODE_IMAGE_TAG} AS build
WORKDIR /app
ENV CI=true NPM_CONFIG_UPDATE_NOTIFIER=false NPM_CONFIG_FUND=false NPM_CONFIG_AUDIT=false
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:${NGINX_IMAGE_TAG}
USER root
RUN rm -rf /usr/share/nginx/html/* /etc/nginx/conf.d/*
COPY nginx.conf /etc/nginx/conf.d/storm-frontend.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chmod -R a+rX /usr/share/nginx/html /etc/nginx/conf.d
USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
