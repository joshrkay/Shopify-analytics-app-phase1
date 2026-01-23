#!/bin/bash
# Load Environment Variables from .env file
#
# Usage: source load_env.sh
# Or: . load_env.sh

if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
    echo "✅ Environment variables loaded"
else
    echo "⚠️  .env file not found"
    echo "   Create .env from .env.example:"
    echo "   cp .env.example .env"
    echo "   # Then edit .env with your credentials"
fi
