FROM node:26.5.0-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY agent/package.json ./agent/package.json
COPY web/package.json ./web/package.json
RUN npm ci --workspace agent --include-workspace-root --ignore-scripts
COPY agent/tsconfig.json ./agent/
COPY agent/src ./agent/src
RUN npm run build --workspace agent && npm prune --omit=dev --workspace agent --include-workspace-root --ignore-scripts

FROM node:26.5.0-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production AGENT_HOST=0.0.0.0 AGENT_PORT=8081
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/agent/package.json ./agent/package.json
COPY --from=build /app/agent/dist ./agent/dist
USER node
CMD ["node", "agent/dist/index.js"]
