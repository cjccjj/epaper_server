import sqlite3
import os

db_path = "data/epaper.db"
sql = """
INSERT OR IGNORE INTO devices (mac_address, api_key, friendly_id, battery_voltage, fw_version, rssi, last_update_time, refresh_rate, timezone, display_width, display_height, active_dish, reddit_config) 
VALUES 
('AA:BB:CC:DD:EE:01', 'fake_key_1', 'DEVICE_EE01', 3.85, 'v1.2.0', -65, datetime('now'), 60, 'America/New_York', 400, 300, 'gallery', '{"subreddit": "EarthPorn", "show_title": true, "bit_depth": 2, "gamma_index": 6, "clip_percent": 20, "cost_percent": 6, "dither_strength": 1.0, "sharpen_amount": 0.0, "auto_optimize": false}'),
('AA:BB:CC:DD:EE:02', 'fake_key_2', 'DEVICE_EE02', 4.12, 'v1.2.1', -45, datetime('now'), 30, 'Europe/London', 800, 480, 'reddit', '{"subreddit": "Art", "show_title": false, "bit_depth": 1, "gamma_index": 0, "clip_percent": 22, "cost_percent": 6, "dither_strength": 1.0, "sharpen_amount": 0.1, "auto_optimize": true}'),
('AA:BB:CC:DD:EE:03', 'fake_key_3', 'DEVICE_EE03', 3.70, 'v1.1.9', -80, datetime('now'), 120, 'Asia/Tokyo', 250, 122, 'gallery', '{"subreddit": "SpacePorn", "show_title": true, "bit_depth": 2, "gamma_index": 6, "clip_percent": 20, "cost_percent": 6, "dither_strength": 1.0, "sharpen_amount": 0.0, "auto_optimize": false}');
"""

if not os.path.exists(db_path):
    print(f"Error: {db_path} not found.")
    exit(1)

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
