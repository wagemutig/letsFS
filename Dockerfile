FROM node:22-slim AS builder

WORKDIR /app/sdk/mcp
COPY sdk/mcp/package.json sdk/mcp/package-lock.json ./
RUN npm ci
COPY sdk/mcp/tsconfig.json ./
COPY sdk/mcp/src/ ./src/
RUN npm run build

FROM node:22-slim AS runtime

WORKDIR /app
COPY --from=builder /app/sdk/mcp/dist/ ./dist/
COPY sdk/mcp/package.json ./package.json
COPY README.md LICENSE ./

ENV NODE_ENV=production
# Amadeus credentials (optional — enables live pricing)
# ENV LETSFS_AMADEUS_KEY=
# ENV LETSFS_AMADEUS_SECRET=

CMD ["node", "dist/index.js"]
