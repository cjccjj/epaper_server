import sqlite3
import os

db_path = "data/epaper.db"
sql_file = "populate.sql"

if not os.path.exists(db_path):
    print(f"Error: {db_path} not found.")
    exit(1)

if not os.path.exists(sql_file):
    print(f"Error: {sql_file} not found.")
    exit(1)

with open(sql_file, "r") as f:
    sql = f.read()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    cursor.executescript(sql)
    conn.commit()
    print("Database populated successfully.")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
