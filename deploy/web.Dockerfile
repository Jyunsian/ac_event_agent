FROM node:26.5.0-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY agent/package.json ./agent/package.json
COPY web/package.json ./web/package.json
RUN npm ci --workspace web --include-workspace-root
COPY web ./web
COPY contracts ./contracts/
COPY tests/fixtures/hand/expected.json tests/fixtures/hand/export.json ./tests/fixtures/hand/
RUN npm run build --workspace web

FROM nginx:1.28-alpine
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/web/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
