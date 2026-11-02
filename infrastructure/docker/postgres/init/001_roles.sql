-- AdVegaX database roles for LOCAL DEVELOPMENT and CI ONLY.
-- Hosted environments create these roles through infrastructure with managed secrets (D15).
-- Runs as the PostgreSQL superuser. Idempotent.
--
--   advegax_migrator  owns the schema; used only by Alembic migrations
--   advegax_app       runtime API role: not owner, not superuser, NOBYPASSRLS
--   advegax_system    worker/system role: narrow grants, NOBYPASSRLS

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'advegax_migrator') THEN
    CREATE ROLE advegax_migrator LOGIN PASSWORD 'advegax_migrator'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'advegax_app') THEN
    CREATE ROLE advegax_app LOGIN PASSWORD 'advegax_app'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'advegax_system') THEN
    CREATE ROLE advegax_system LOGIN PASSWORD 'advegax_system'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END
$$;
