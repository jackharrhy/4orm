#!/usr/bin/env bash
# Pull the production database and uploads to local for testing.
# Usage: ./scripts/pull-prod.sh

set -euo pipefail

REMOTE="jack@newport"
REMOTE_BASE="infra/hosts/newport/volumes"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Pulling database..."
rsync -avz --progress "$REMOTE:$REMOTE_BASE/4orm_data/4orm.db" "$LOCAL_DIR/data/4orm.db"

echo ""
echo "==> Pulling uploads..."
rsync -avz --progress --delete --exclude=".gitkeep" "$REMOTE:$REMOTE_BASE/4orm_uploads/" "$LOCAL_DIR/uploads/"

echo ""
echo "Done. You can now run: uv run uvicorn app.main:app --reload"
