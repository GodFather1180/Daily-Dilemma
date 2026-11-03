#!/bin/bash
set -e

# Run migrations first
alembic upgrade head || exit 1

# Automatically seed scenarios ONLY if the game_scenarios table is empty
python - << 'EOF'
import os
from sqlalchemy import create_engine, text

host = os.environ.get("POSTGRES_HOST") or os.environ.get("DATABASE_HOST")
user = os.environ.get("POSTGRES_USER") or os.environ.get("DATABASE_USER")
password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("DATABASE_PASSWORD")
dbname = os.environ.get("POSTGRES_DB") or os.environ.get("DATABASE_NAME") or user

url = f"postgresql+psycopg2://{user}:{password}@{host}:5432/{dbname}"
print("Connecting to DB for seeding check:", url)

engine = create_engine(url)

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM game_scenarios"))
        count = result.scalar()
        if count is None:
            print("game_scenarios table exists but COUNT(*) returned None; skipping seeding.")
        elif count == 0:
            print("game_scenarios is empty — running seed_game_data.py …")
            os.system("python scripts/seed_game_data.py")
        else:
            print(f"game_scenarios already has {count} rows; skipping seed.")
except Exception as e:
    # If the table doesn't exist yet or something else goes wrong, just log it and continue.
    print("Error checking or seeding scenarios:", e)
EOF

exec "$@"
