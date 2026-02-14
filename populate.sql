INSERT OR IGNORE INTO devices (mac_address, api_key, friendly_id, battery_voltage, fw_version, rssi, last_update_time, refresh_rate, timezone, display_width, display_height, active_dish) 
VALUES 
('AA:BB:CC:DD:EE:01', 'fake_key_1', 'DEVICE_EE01', 3.85, 'v1.2.0', -65, datetime('now'), 60, 'America/New_York', 400, 300, 'gallery'),
('AA:BB:CC:DD:EE:02', 'fake_key_2', 'DEVICE_EE02', 4.12, 'v1.2.1', -45, datetime('now'), 30, 'Europe/London', 800, 480, 'gallery'),
('AA:BB:CC:DD:EE:03', 'fake_key_3', 'DEVICE_EE03', 3.70, 'v1.1.9', -80, datetime('now'), 120, 'Asia/Tokyo', 250, 122, 'gallery');

INSERT OR IGNORE INTO rss_sources (mac_address, url, name, config)
VALUES
('AA:BB:CC:DD:EE:01', 'https://www.theverge.com/rss/index.xml', 'The Verge', '{"bit_depth": 2, "auto_optimize": true}'),
('AA:BB:CC:DD:EE:02', 'https://feeds.feedburner.com/design-milk', 'Design Milk', '{"bit_depth": 1, "auto_optimize": false}');
