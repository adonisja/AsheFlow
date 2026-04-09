#!/bin/bash

# Navigate to the directory where the script is located (project root)
cd "$(dirname "$0")"

echo "🚀 Starting AsheFlow Backend (Database, Redis, FastAPI)..."
docker-compose up -d

echo ""
echo "🌐 Starting AsheFlow Frontend (Vite/React)..."
echo "Press ^C (Ctrl+C) to stop the frontend server."
echo ""

cd frontend && npm run dev