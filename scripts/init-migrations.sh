#!/bin/sh
# Applied by the postgres docker-entrypoint on FIRST initialization of an
# empty data volume only (docker-entrypoint-initdb.d scripts never run
# against an existing volume) — existing dev volumes are unaffected, since
# they were already brought up to date via scripts/setup.sh's
# run_migrations. This script exists so a fresh `make infra` (without
# setup.sh) still ends up with the full schema.
#
# Applies every scripts/migrations/*.sql (mounted read-only at /migrations)
# in sorted order, including 006_ml_models.sql (ORPHANED — the ML stack was
# deleted, but the tables are harmless and applying it keeps the
# applied-migrations history consistent).
set -e

for f in /migrations/*.sql; do
    [ -f "$f" ] || continue
    echo "Applying migration: $(basename "$f")"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
