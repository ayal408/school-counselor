FROM node:22-alpine AS build
WORKDIR /app
COPY counselor-client/package*.json ./
RUN npm ci
COPY counselor-client/ ./
RUN npm run build
FROM nginx:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
