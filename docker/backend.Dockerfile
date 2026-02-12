###############################################################################
# Stage 1: Build the React frontend
###############################################################################
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend

# Copy dependency files first for caching
COPY frontend/package.json frontend/package-lock.json ./
# Use npm install instead of npm ci because package.json may have
# dependencies not yet reflected in the lock file (e.g. @clerk/clerk-react).
# This updates the lock file in the container and installs everything.
RUN npm install

# Copy frontend source and build
COPY frontend/ ./

# VITE_CLERK_PUBLISHABLE_KEY is a public key (pk_test_/pk_live_) that must
# be baked into the frontend bundle at build time.
# Hardcoded here because Render's Docker build does not reliably pass
# build-args or preserve .env files in the build context.
RUN VITE_CLERK_PUBLISHABLE_KEY="pk_test_d2VsY29tZS1sYW1iLTM3LmNsZXJrLmFjY291bnRzLmRldiQ" npx vite build

# Build: if build-arg is provided use it, otherwise source .env.production
RUN echo "==> .env.production contents:" && cat .env.production 2>/dev/null || echo "(file not found)" \
    && echo "==> Build-arg value length: $(echo -n "$VITE_CLERK_PUBLISHABLE_KEY" | wc -c)" \
    && if [ -n "$VITE_CLERK_PUBLISHABLE_KEY" ]; then \
         echo "==> Using VITE_CLERK_PUBLISHABLE_KEY from build arg"; \
       elif [ -f .env.production ]; then \
         echo "==> Sourcing .env.production"; \
         set -a && . ./.env.production && set +a; \
       else \
         echo "==> WARNING: No key source found!"; \
       fi \
    && echo "==> Final VITE_CLERK_PUBLISHABLE_KEY length: $(echo -n "$VITE_CLERK_PUBLISHABLE_KEY" | wc -c)" \
    && npx vite build


###############################################################################
# Stage 2: Python backend + built frontend static files
###############################################################################
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps if needed (psycopg2 etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first for caching
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY backend /app/backend

# Copy built frontend from stage 1 into backend/static
COPY --from=frontend-build /app/frontend/dist /app/backend/static

# Ensure python can import /app/backend/src
ENV PYTHONPATH=/app/backend

# Change to backend directory and run uvicorn
WORKDIR /app/backend

# Render listens on $PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
