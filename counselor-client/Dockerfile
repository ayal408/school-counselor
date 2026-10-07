# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY counselor-client/package*.json ./
COPY counselor-client/scripts/ ./scripts/
RUN --mount=type=secret,id=local_ca \
    if [ -s /run/secrets/local_ca ]; then \
      NODE_EXTRA_CA_CERTS=/run/secrets/local_ca npm ci; \
    else npm ci; fi
COPY counselor-client/ ./
RUN npm run build
FROM nginx:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
