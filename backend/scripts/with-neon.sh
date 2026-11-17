#!/usr/bin/env bash
# Run a command against the Neon database instead of local Postgres.
#   scripts/with-neon.sh uv run alembic upgrade head
# Reads DATABASE_URL / DATABASE_URL_UNPOOLED from the repo-root .env.local
# (written by `neon init`) without printing them.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
envfile="$here/../.env.local"
[[ -f "$envfile" ]] || { echo "missing $envfile (run neon init)" >&2; exit 1; }
set -a; source "$envfile"; set +a
export PLANNER_DATABASE_URL="$DATABASE_URL"
export PLANNER_MIGRATION_DATABASE_URL="${DATABASE_URL_UNPOOLED:-$DATABASE_URL}"
cd "$here"
exec "$@"
