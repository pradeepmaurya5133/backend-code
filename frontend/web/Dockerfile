# Subh AI web client, served by nginx.
# Build context is frontend/ (not frontend/web/) because the app imports the
# shared API client from ../shared.

FROM node:22-alpine AS builder
WORKDIR /src
COPY web/package.json web/
RUN cd web && npm install
COPY shared ./shared
COPY web ./web
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN cd web && npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=builder /src/web/dist /usr/share/nginx/html
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
