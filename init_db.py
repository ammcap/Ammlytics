# init_db.py
from dotenv import load_dotenv
load_dotenv() # This loads variables from your .env file

import os
from sqlalchemy import create_engine, text

# This line reads the DATABASE_URL you just set in Render's Environment tab
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise Exception("Error: DATABASE_URL environment variable is not set.")

# This line sets up the connection to your PostgreSQL database
engine = create_engine(DATABASE_URL)

# This is the command to create your table, which works perfectly for PostgreSQL
create_table_sql = """
CREATE TABLE IF NOT EXISTS initial_positions (
    token_id TEXT PRIMARY KEY,
    creation_date TEXT NOT NULL,
    block_number INTEGER NOT NULL,
    amount0 TEXT NOT NULL,
    amount1 TEXT NOT NULL,
    price TEXT NOT NULL
);
"""

# This block connects to the database and runs the command
with engine.connect() as connection:
    connection.execute(text(create_table_sql))
    connection.commit()

print("✅ Database table 'initial_positions' is ready.")