# E-Paper Server

A specialized FastAPI backend for managing E-paper display devices, featuring automated RSS feed fetching, multi-source management, and custom image processing.

## 🚀 Overview

This project serves as a central hub for E-paper devices. It manages device registration, monitors battery levels, and provides processed (dithered) images for low-power displays. The server supports multiple RSS sources per device, allowing for diverse content delivery including news, art, and information feeds.

## 🛠 Tech Stack

- **Backend**: Python 3.x with **FastAPI**.
- **Database**: **SQLite** (via SQLAlchemy) for device metadata, RSS sources, and logs.
- **Task Scheduling**: Async background tasks for RSS fetching and image optimization.
- **Image Processing**: Custom dithering logic to convert web images into display-ready `.bmp` files.
- **Frontend**: A lightweight HTML/JavaScript Admin Dashboard powered by **Alpine.js**.
- **Containerization**: **Docker** and **Docker Compose**.

## 📁 Project Structure

- `main.py`: Core API logic, RSS fetcher coordination, and background task management.
- `database.py`: SQLAlchemy models for Devices, RSS Sources, Images, and Logs.
- `rss_general_fetcher.py`: Generic RSS fetching logic with image extraction and AI optimization.
- `image_processor.py`: Logic for downloading, resizing, and dithering images.
- `static/`: Contains the Admin UI (`admin.html`) and CSS/JS assets.
- `data/`: Persistent storage for the SQLite database (`epaper.db`) and RSS caches.
- `bitmaps/`: Storage for processed `.bmp` images ready for device download.

## 📰 RSS Management

The server allows each device to manage up to **5 RSS sources**. Each source can be individually configured:

1.  **Source Configuration**:
    *   **URL**: Any valid RSS feed URL.
    *   **Name**: Custom name for easy identification.
    *   **AI Optimization**: Toggle to use AI for better image extraction and captioning.
    *   **Display Settings**: Bit-depth and dithering preferences.
2.  **Fetching & Caching**:
    *   Caches are maintained per device and per source to ensure fast delivery.
    *   Images are automatically processed and dithered for the specific device's display capabilities.

## ⚙️ Configuration

- **Admin Password**: Set via the `ADMIN_PASSWORD` environment variable.
- **Base URL**: Set via `BASE_URL` for correctly linking processed images.

## 🖥 Admin Dashboard

Accessible at `http://<server-ip>:4200/admin`.
- Monitor device status (Battery, RSSI, Last Seen).
- Manage multiple RSS sources per device.
- Preview processed RSS content.
- Upload and manage a personal image gallery.
- Configure device-specific settings (Timezone, Refresh Rate, Display Dimensions).

## 🚢 Deployment

Run the project using Docker Compose:

```bash
docker-compose up -d
```

The server listens on port **4200**.

## 💾 Data Management

- **Persistence**: Both the `data/` and `bitmaps/` directories are mapped to host volumes.
- **Cleanup**: The server automatically manages processed images to stay within storage limits.

---
*Documentation updated on 2026-02-13*
