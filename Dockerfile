FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY src/aura/workspace/web/frontend/package.json src/aura/workspace/web/frontend/package-lock.json ./
RUN npm ci
COPY src/aura/workspace/web/frontend/ ./
RUN npm run build
RUN npm prune --omit=dev

FROM python:3.12-slim-bookworm AS runtime
ARG AURA_BUILD_COMMIT=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 \
    AURA_CLOUD_MODE=true AURA_WORKSPACE_HOST=0.0.0.0 AURA_VERSION=0.1.0 \
    AURA_BUILD_COMMIT=${AURA_BUILD_COMMIT}
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY --from=frontend /build/representation/ ./src/aura/workspace/web/representation/
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
RUN pip install --no-cache-dir ".[server,vertex,cloud]" && \
    addgroup --system aura && adduser --system --ingroup aura --home /app aura && \
    chown -R aura:aura /app
COPY --from=frontend /build/frontend/node_modules/ /usr/local/lib/python3.12/site-packages/aura/workspace/web/frontend/node_modules/
RUN printf '{"components":[{"reference":"U1","semanticId":"component-controller","kind":"controller","pins":["VCC","GND"]}],"connections":[]}' | node /usr/local/lib/python3.12/site-packages/aura/workspace/web/frontend/generators/tscircuit/generate-circuit.mjs >/tmp/circuit-smoke.json && \
    grep -q '"status":"ready"' /tmp/circuit-smoke.json && rm /tmp/circuit-smoke.json
USER aura
EXPOSE 8080
CMD ["aura", "--host", "0.0.0.0"]
