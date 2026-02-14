# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Workflow

**Primary Development Approach: Docker-Only**
- We aim to build, run, and test **ONLY with Docker** for complete environment consistency
- Local development environment is limited, especially for AI features that require proper API key configuration
- Basic functionality can be tested locally, but comprehensive testing must be done in Docker environment
- After basic local testing confirms functionality, git push to remote repository
- Full testing is performed on the remote production server, and results are reported back

## Development Commands

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the server locally
python main.py

# Run with uvicorn (alternative)
uvicorn main:app --reload --host 0.0.0.0 --port 4200
```

### Docker Development
```bash
# Build and start containers
docker-compose up -d --build

# View logs
docker logs epaper_server -f

# Stop containers
docker-compose down
```

### Environment Variables
- `ADMIN_PASSWORD`: Admin dashboard password (default: "z0000l")
- `BASE_URL`: Base URL for image links (required for production)
- `OPENAI_API_KEY`: Required for AI image optimization features

## Code Architecture

### Core Components
1. **FastAPI Backend** (`main.py`): Handles all API endpoints, device registration, display logic, and admin functionality
2. **Database Layer** (`database.py`): SQLite database with SQLAlchemy ORM for:
   - Device metadata and status tracking
   - RSS source management (up to 5 per device)
   - Image metadata and gallery management
   - Device logs
3. **RSS Processing** (`rss_general_fetcher.py`): Generic RSS feed fetching, parsing, and AI optimization pipeline
4. **Image Processing** (`image_processor.py`): Downloads, resizes, and dithers images for e-paper displays

### Key Directories
- `static/`: Admin dashboard HTML, CSS, and JavaScript (Alpine.js)
- `bitmaps/`: Processed `.bmp` files ready for device download (excluded from git)
- `data/`: SQLite database and RSS cache files (excluded from git)

### Data Flow
1. **Device Registration**: Devices register via `/api/setup` with MAC address
2. **Content Delivery**: Devices request images via `/api/display` which:
   - Updates device status metrics
   - Selects content from enabled sources (gallery or RSS feeds)
   - Returns URL to processed bitmap
3. **Admin Management**: Admin dashboard (`/admin`) allows:
   - Device monitoring and configuration
   - RSS source management and manual refreshing
   - Image gallery uploads and management
   - Real-time RSS preview and cache management

### Critical Files to Reference
- `main.py`: Primary API logic and routing
- `database.py`: Database models and schema migrations
- `rss_general_fetcher.py`: RSS processing pipeline (shared between Reddit and generic RSS)
- `image_processor.py`: Image processing and dithering logic
- `static/admin.html`: Admin dashboard UI structure
- `static/js/admin_app.js`: Admin dashboard Alpine.js application logic

## Deployment Notes
- Production deployment uses Docker with persistent volumes for `bitmaps/` and `data/`
- Admin password must be set via `ADMIN_PASSWORD` environment variable
- `BASE_URL` must be configured for correct image URLs in production
- Server listens on port 4200 by default

## Important Patterns
- **Device Identification**: All device operations use MAC address as primary identifier
- **Content Selection**: Devices can have multiple enabled sources ("dishes") with sequence/random display modes
- **RSS Caching**: Each RSS source has its own cache file per device (`data/rss_cache_{mac}_{source_id}.json`)
- **Image Processing**: All images are processed to device-specific dimensions and bit depths before serving
- **Session Management**: Admin uses simple cookie-based session authentication