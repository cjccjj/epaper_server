# E-Paper Server

A specialized FastAPI backend for managing E-paper display devices, featuring automated image fetching from Reddit and custom image processing.

## 🚀 Overview

This project serves as a central hub for E-paper devices. It manages device registration, monitors battery levels, and provides processed (dithered) images for low-power displays. The highlight is an automated Reddit image harvester that selects high-quality content based on specific strategies.

## 🛠 Tech Stack

- **Backend**: Python 3.x with **FastAPI**.
- **Database**: **SQLite** (via SQLAlchemy) for device metadata and logs.
- **Task Scheduling**: Async background tasks for Reddit fetching.
- **Image Processing**: Custom dithering logic to convert web images into display-ready `.bmp` files.
- **Frontend**: A lightweight HTML/JavaScript Admin Dashboard.
- **Containerization**: **Docker** and **Docker Compose**.

## 📁 Project Structure

- `main.py`: Core API logic, Reddit fetcher, and background task management.
- `database.py`: SQLAlchemy models for Devices, Images, and Logs.
- `image_processor.py`: Logic for downloading, resizing, and dithering images.
- `static/`: Contains the Admin UI (`admin.html`) and CSS/JS assets.
- `data/`: Persistent storage for the SQLite database (`epaper.db`) and Reddit state (`reddit_cache.json`).
- `bitmaps/`: Storage for processed `.bmp` images ready for device download.

## 🤖 Reddit Fetching Strategy

The server automatically refreshes its Reddit image cache every **3 hours**. It uses a mixed strategy to balance fresh content with "all-time classics":

1.  **Recent Posts**:
    *   Sources: `Top-Today` and `Uprising`.
    *   Target: 8 images from each.
    *   Behavior: Reuses existing cache entries if they are still relevant to avoid redundant processing.
2.  **Old Good Posts**:
    *   Sources: `Top-Week` (4), `Top-Month` (3), `Top-Year` (2).
    *   Behavior: Rotates content. If an item is already in the cache, it is skipped to ensure the display stays fresh.
3.  **Processing Rules**:
    *   Avoids duplicates within a single fetch batch.
    *   Limits processing to the first 25 entries per list to prevent long-running tasks.
    *   Atomic updates: The cache only updates if at least one new image is successfully processed.

## ⚙️ Configuration

- **Admin Password**: Set via the `ADMIN_PASSWORD` environment variable in `docker-compose.yml`.
- **Fetch Rate**: Hardcoded to 3 hours in `main.py` but persisted in `data/reddit_cache.json`.
- **Subreddit**: Configurable via the Admin UI (defaults to `memes`).

## 🖥 Admin Dashboard

Accessible at `http://<server-ip>:4200/static/admin.html`.
- Monitor device status (Battery, RSSI, Last Seen).
- Preview processed Reddit images.
- Manually trigger a "Fetch Now" to update the cache.
- Configure device-specific settings (Timezone, Refresh Rate).

## 🚢 Deployment

Run the project using Docker Compose:

```bash
docker-compose up -d
```

The server listens on port **4200**.

## 💾 Data Management

- **Persistence**: Both the `data/` and `bitmaps/` directories are mapped to host volumes for persistence across container restarts.
- **Cleanup**: The server automatically deletes orphaned `.bmp` files that are no longer referenced in the Reddit cache.

---
*Documentation generated on 2026-01-24*
