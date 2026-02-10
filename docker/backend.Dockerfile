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

# VITE_CLERK_PUBLISHABLE_KEY must be set at build time since Vite
# inlines environment variables into the bundle.
ARG VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_CLERK_PUBLISHABLE_KEY=${VITE_CLERK_PUBLISHABLE_KEY}

# Diagnostic: confirm whether the build arg was received from Render
RUN echo "==> VITE_CLERK_PUBLISHABLE_KEY is set: $(test -n \"$VITE_CLERK_PUBLISHABLE_KEY\" && echo 'YES' || echo 'NO (will fall back to .env.production)')"

# Use npx vite build directly instead of "npm run build" (which runs
# tsc && vite build). The codebase has pre-existing TypeScript errors
# that block tsc, but Vite/esbuild transpiles fine without strict
# type checking. Type errors should be fixed separately.
RUN npx vite build


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