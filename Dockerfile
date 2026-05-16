FROM node:20-slim AS builder

WORKDIR /app

COPY package.json .
RUN npm ci --omit=dev

# Final stage
FROM node:20-slim

WORKDIR /app

RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app

COPY --from=builder --chown=botuser:botuser /app/node_modules ./node_modules
COPY --chown=botuser:botuser package.json .
COPY --chown=botuser:botuser js/ ./js/

USER botuser

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD node -e "require('http').get('http://localhost:8443/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "js/webhookServer.js"]
