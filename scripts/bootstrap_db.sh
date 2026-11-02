#!/usr/bin/env bash
# Create AdVegaX roles and databases for local development or CI.
# Usage: PGHOST=... PGUSER=<superuser> PGPASSWORD=... scripts/bootstrap_db.sh <database> [<database> ...]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
psql -v ON_ERROR_STOP=1 -d postgres -f "$here/../infrastructure/docker/postgres/init/001_roles.sql"
for db in "$@"; do
  exists="$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'" -d postgres)"
  if [ "$exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE \"$db\" OWNER advegax_migrator"
  fi
  psql -v ON_ERROR_STOP=1 -d "$db" <<SQL
REVOKE ALL ON DATABASE "$db" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$db" TO advegax_migrator, advegax_app, advegax_system;
ALTER SCHEMA public OWNER TO advegax_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO advegax_app, advegax_system;
SQL
done
