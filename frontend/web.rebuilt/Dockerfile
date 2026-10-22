# Build context is ./frontend (see docker-compose.yml), not ./frontend/web, so
# that the shared API client in ../shared is inside the context.
#
# Not built in this repo's environment: Docker is not installed here. The same
# build runs locally with `npm run build`.

FROM node:22-alpine AS build
WORKDIR /app

# Dependencies first, so a source-only change does not reinstall them.
COPY web/package.json web/package-lock.json* ./web/
RUN cd web && (npm ci || npm install)

COPY shared/ ./shared/
COPY web/ ./web/

# Baked in at build time: Vite inlines import.meta.env, so the API base cannot
# be changed after the image is built.
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN cd web && npm run build

FROM nginx:1.27-alpine
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost/ >/dev/null || exit 1
