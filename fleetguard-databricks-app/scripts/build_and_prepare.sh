#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# build_and_prepare.sh
# Build the React frontend and copy into static/ for Databricks
# Run from the project root (capstone-FleetGuardAI-main/)
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATABRICKS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$DATABRICKS_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/fleetguard-frontend"
STATIC_DIR="$DATABRICKS_DIR/static"

echo "==> Installing frontend dependencies..."
cd "$FRONTEND_DIR"
npm install

echo "==> Building frontend..."
npm run build

echo "==> Cleaning old static files..."
rm -rf "$STATIC_DIR"/*

echo "==> Copying build output to static/..."
cp -r "$FRONTEND_DIR/dist/"* "$STATIC_DIR/"

echo ""
echo "✅  Build complete!"
echo "    Static files: $STATIC_DIR"
echo ""
echo "Next steps:"
echo "  1. Edit app.yaml with your env vars (MYSQL_HOST, MYSQL_PASSWORD, etc.)"
echo "  2. Deploy:  databricks apps deploy <app-name> --source-code-path $DATABRICKS_DIR"
