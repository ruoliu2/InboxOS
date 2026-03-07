#!/bin/sh
set -eu

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-postgres}"
DB_USER="${DB_USER:-postgres}"

for file in /workspace/supabase/migrations/*.sql; do
  if [ -f "$file" ]; then
    echo "Applying migration: $file"
    psql \
      --host "$DB_HOST" \
      --port "$DB_PORT" \
      --username "$DB_USER" \
      --dbname "$DB_NAME" \
      --set ON_ERROR_STOP=1 \
      --file "$file"
  fi
done

if [ -f /workspace/supabase/seed.sql ]; then
  echo "Applying seed: /workspace/supabase/seed.sql"
  psql \
    --host "$DB_HOST" \
    --port "$DB_PORT" \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    --set ON_ERROR_STOP=1 \
    --file /workspace/supabase/seed.sql
fi
