from sqlalchemy import create_engine, Column, String, Float, DateTime, Boolean, Integer, JSON, ForeignKey, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import datetime
import uuid
import os

# Using a 'data' folder for the production database
os.makedirs("data", exist_ok=True)
SQLALCHEMY_DATABASE_URL = "sqlite:///./data/epaper.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Device(Base):
    __tablename__ = "devices"

    mac_address = Column(String, primary_key=True, index=True)
    api_key = Column(String, unique=True, index=True)
    friendly_id = Column(String, unique=True)
    
    # Status tracking
    battery_voltage = Column(Float, nullable=True)
    fw_version = Column(String, nullable=True)
    rssi = Column(Integer, nullable=True)
    last_update_time = Column(DateTime, default=datetime.datetime.utcnow)
    next_expected_update = Column(DateTime, nullable=True)
    last_refresh_duration = Column(Integer, nullable=True)
    
    # Playlist tracking
    current_image_index = Column(Integer, default=0)
    refresh_rate = Column(Integer, default=60)
    timezone = Column(String, default="UTC")
    display_width = Column(Integer, default=400)
    display_height = Column(Integer, default=300)
    active_dish = Column(String, default="gallery")
    reddit_config = Column(JSON, default=lambda: {"subreddit": "aww", "sort": "top", "time": "day"})
    
    # Relationships
    images = relationship("DeviceImage", back_populates="device", cascade="all, delete-orphan")

class DeviceImage(Base):
    __tablename__ = "device_images"

    id = Column(Integer, primary_key=True, index=True)
    mac_address = Column(String, ForeignKey("devices.mac_address"))
    filename = Column(String)
    original_name = Column(String)
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    device = relationship("Device", back_populates="images")

class DeviceLog(Base):
    __tablename__ = "device_logs"

    id = Column(Integer, primary_key=True, index=True)
    mac_address = Column(String, index=True)
    message = Column(String)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

def run_migrations():
    """Run simple migrations to update schema if needed."""
    inspector = inspect(engine)
    if "devices" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("devices")]
        if "timezone" not in columns:
            print("Migration: Adding 'timezone' column to 'devices' table")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE devices ADD COLUMN timezone TEXT DEFAULT 'UTC'"))
                conn.commit()
        if "display_width" not in columns:
            print("Migration: Adding 'display_width' column to 'devices' table")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE devices ADD COLUMN display_width INTEGER DEFAULT 400"))
                conn.commit()
        if "display_height" not in columns:
            print("Migration: Adding 'display_height' column to 'devices' table")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE devices ADD COLUMN display_height INTEGER DEFAULT 300"))
                conn.commit()

def init_db():
    Base.metadata.create_all(bind=engine)
    run_migrations()

