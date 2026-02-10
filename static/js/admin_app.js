/**
 * admin_app.js
 * Alpine.js state management for the E-Paper Server Admin UI.
 * Handles device management, gallery uploads, and Reddit RSS configuration.
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('adminApp', () => ({
        // --- Core State ---
        devices: [],
        currentMac: localStorage.getItem('lastSelectedMac') || '',
        activeDish: 'gallery',
        currentTab: localStorage.getItem('lastSelectedTab') || 'gallery',
        
        // --- Device Settings ---
        // Basic hardware and metadata for the e-paper device
        deviceSettings: {
            name: '',
            refresh_rate: 30,
            display_width: 400,
            display_height: 300,
            timezone: 'UTC'
        },
        
        // --- Gallery Management ---
        // State for uploading and processing local images
        img: null, // Holds the current selected Image object for preview
        galleryItems: [],
        galleryConfig: {
            bitDepth: 'fs4g',
            clip: 22,
            cost: 6,
            gamma: 0, // Index into gammaLabels
            sharpen: 0.1,
            ditherStrength: 100
        },
        stats: '',
        
        // --- Reddit Integration ---
        // Configuration for AI-optimized Reddit RSS fetching
        redditConfig: {
            subreddit: '',
            bit_depth: 2,
            gamma_index: 6,
            clip_percent: 20,
            cost_percent: 6,
            sharpen_amount: 0.2,
            dither_strength: 1.0,
            auto_optimize: true,
            ai_prompt: ''
            // show_title removed: decision is now AI-only
        },
        redditPreview: [],
        redditStatus: 'Ready',
        isFetchingReddit: false,
        
        // --- UI State Helpers ---
        isAnalyzingAI: false,
        isUploading: false,
        aiInfo: '',
        gammaLabels: [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4],

        /**
         * Initialize the application.
         * Sets up image preview listeners and restores last selected device/tab.
         */
        async init() {
            this.img = new Image();
            this.img.onload = () => this.processImage();
            this.img.onerror = () => {
                if (this.img.src && !this.img.src.startsWith('data:image/png;base64,iVBOR')) {
                    alert("Failed to load image.");
                }
            };

            await this.fetchDevices();
            
            // Restore last state from localStorage
            if (this.currentMac) {
                await this.selectDevice(this.currentMac);
            }
            
            this.showTab(this.currentTab);

            // Global click handler for the image overlay modal
            window.addEventListener('click', (e) => {
                if (e.target.id === 'overlay') {
                    e.target.style.display = 'none';
                }
            });
        },

        // --- Device Operations ---

        /**
         * Fetch the list of registered devices from the backend.
         */
        async fetchDevices() {
            try {
                const res = await fetch('/admin/devices');
                this.devices = await res.json();
            } catch (e) {
                console.error("Failed to fetch devices:", e);
            }
        },

        /**
         * Select a device and load its specific configurations.
         */
        async selectDevice(mac) {
            this.currentMac = mac;
            localStorage.setItem('lastSelectedMac', mac);
            
            const device = this.devices.find(d => d.mac_address === mac);
            if (device) {
                this.deviceSettings = {
                    name: device.name,
                    refresh_rate: device.refresh_rate,
                    display_width: device.display_width,
                    display_height: device.display_height,
                    timezone: device.timezone
                };
                this.activeDish = device.active_dish || 'gallery';
                
                await this.loadGallery();
                if (this.currentTab === 'reddit') {
                    await this.loadRedditConfig();
                }
            }
        },

        /**
         * Save basic device settings to the server.
         */
        async saveDeviceSettings() {
            if (!this.currentMac) return;
            try {
                const payload = { 
                    ...this.deviceSettings,
                    reddit_config: this.redditConfig 
                };
                await fetch(`/admin/device/${this.currentMac}/settings`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                await this.fetchDevices();
            } catch (e) {
                console.error("Failed to save settings:", e);
            }
        },

        /**
         * Change the active 'dish' (content source) for the current device.
         */
        async setActiveDish(dish) {
            this.activeDish = dish;
            await fetch(`/admin/device/${this.currentMac}/settings`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ active_dish: dish })
            });
            const d = this.devices.find(x => x.mac_address === this.currentMac);
            if (d) d.active_dish = dish;
        },

        // --- UI Navigation ---

        /**
         * Switch between admin tabs (Gallery, Reddit, Settings).
         */
        async showTab(tab) {
            this.currentTab = tab;
            localStorage.setItem('lastSelectedTab', tab);
            
            if (tab === 'reddit' && this.currentMac) {
                await this.loadRedditConfig();
            }
        },

        // --- Gallery Image Processing ---

        /**
         * Load gallery images for the current device.
         */
        async loadGallery() {
            if (!this.currentMac) return;
            const device = this.devices.find(d => d.mac_address === this.currentMac);
            if (device) {
                this.galleryItems = device.images || [];
            }
        },

        /**
         * Handle local file selection for gallery upload.
         */
        handleFileUpload(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            const reader = new FileReader();
            reader.onload = (ev) => {
                this.img.src = ev.target.result;
            };
            reader.readAsDataURL(file);
        },

        /**
         * Process the current image using the client-side ImageProcess library.
         * Updates the preview canvases.
         */
        processImage() {
            if (!this.img || !this.img.src || this.img.src.length < 100) return;
            
            const canvases = {
                original: document.getElementById('cOriginal'),
                dithered: document.getElementById('cDither')
            };
            
            if (!canvases.original || !canvases.dithered) return;

            const options = {
                width: parseInt(this.deviceSettings.display_width),
                height: parseInt(this.deviceSettings.display_height),
                bitDepth: this.galleryConfig.bitDepth,
                clipPct: parseInt(this.galleryConfig.clip || 0) / 100,
                costPct: parseInt(this.galleryConfig.cost || 0) / 100,
                gamma: this.gammaLabels[parseInt(this.galleryConfig.gamma || 0)],
                sharpen: parseFloat(this.galleryConfig.sharpen || 0),
                ditherStrength: parseInt(this.galleryConfig.ditherStrength || 0) / 100
            };
 
            ImageProcess.process(this.img, canvases, options);
        },

        /**
         * Trigger client-side AI analysis to suggest optimal processing parameters.
         */
        async aiOptimize() {
            if (!this.img || !this.img.src) {
                alert("Please select an image first.");
                return;
            }

            this.isAnalyzingAI = true;
            this.aiInfo = "AI is analyzing image...";
            
            try {
                // Resize for AI analysis to keep payload small
                const tempCanvas = document.createElement('canvas');
                const ctx = tempCanvas.getContext('2d');
                const tw = parseInt(this.deviceSettings.display_width);
                const th = parseInt(this.deviceSettings.display_height);
                
                const scale = Math.max(tw / this.img.width, th / this.img.height);
                const nw = this.img.width * scale;
                const nh = this.img.height * scale;
                const ox = (tw - nw) / 2;
                const oy = (th - nh) / 2;
                
                tempCanvas.width = tw;
                tempCanvas.height = th;
                ctx.drawImage(this.img, ox, oy, nw, nh);
                
                const blob = await new Promise(resolve => tempCanvas.toBlob(resolve, 'image/jpeg', 0.8));
                const fd = new FormData();
                fd.append('file', blob, 'analyze.jpg');
                
                const res = await fetch('/admin/analyze_style', { method: 'POST', body: fd });
                const style = await res.json();
                
                if (style && !style.error) {
                    // Mapping AI classification to technical parameters
                    let sh = 0.2;
                    if (style.has_text_overlay || style.content_type === "text_heavy") sh = 1.0;
                    else if (style.content_type === "comic_illustration") sh = 0.5;
                    
                    let dt = 1.0;
                    if (style.gradient_complexity === "low") dt = 0.4;
                    
                    let gmIndex = (style.content_type === "comic_illustration") ? 6 : 0; // 6=2.2, 0=1.0

                    this.galleryConfig.sharpen = sh;
                    this.galleryConfig.ditherStrength = dt * 100;
                    this.galleryConfig.gamma = gmIndex;
                    
                    const gammaVal = (this.gammaLabels && this.gammaLabels[gmIndex] !== undefined) ? this.gammaLabels[gmIndex].toFixed(1) : '1.0';
                    const applied = `sh:${Math.round(sh*100)}% dt:${Math.round(dt*100)}% gm:${gammaVal}`;
                    this.aiInfo = `${style.content_type} | ${applied}`;
                    
                    this.processImage();
                } else {
                    this.aiInfo = "AI Analysis failed: " + (style.error || "Unknown error");
                }
            } catch (e) {
                console.error("AI Analysis failed:", e);
                this.aiInfo = "AI Analysis failed.";
            } finally {
                this.isAnalyzingAI = false;
            }
        },

        /**
         * Upload the processed image from the dithered canvas to the gallery.
         */
        async uploadToGallery() {
            const canvas = document.getElementById('cDither');
            if (!canvas || !this.currentMac) return;

            this.isUploading = true;
            const bitDepth = this.galleryConfig.bitDepth;
            const pngData = ImageProcess.canvasToPNG(canvas, bitDepth);
            
            const blob = new Blob([pngData], { type: 'image/png' });
            const fd = new FormData();
            fd.append('file', blob, 'image.png');
            
            try {
                const res = await fetch(`/admin/upload/${this.currentMac}`, {
                    method: 'POST',
                    body: fd
                });
                if (res.ok) {
                    await this.fetchDevices();
                    await this.loadGallery();
                } else {
                    alert("Upload failed.");
                }
            } catch (e) {
                console.error("Upload error:", e);
                alert("Upload error.");
            } finally {
                this.isUploading = false;
            }
        },

        /**
         * Delete a specific image from the gallery.
         */
        async deleteImage(imageId) {
            if (!confirm("Delete this image?")) return;
            try {
                const res = await fetch(`/admin/image/${imageId}`, { method: 'DELETE' });
                if (res.ok) {
                    await this.fetchDevices();
                    await this.loadGallery();
                }
            } catch (e) {
                console.error("Delete error:", e);
            }
        },

        /**
         * Show full-size image in the overlay modal.
         */
        showOverlay(url) {
            const overlay = document.getElementById('overlay');
            const overlayImg = document.getElementById('overlayImg');
            overlayImg.src = url;
            overlay.style.display = 'flex';
        },

        // --- Reddit RSS Management ---

        /**
         * Load Reddit RSS configuration for the current device.
         */
        async loadRedditConfig() {
            if (!this.currentMac) return;
            const device = this.devices.find(d => d.mac_address === this.currentMac);
            if (device && device.reddit_config) {
                this.redditConfig = device.reddit_config;
            }
            await this.loadRedditPreview();
        },

        /**
         * Save Reddit configuration to the server.
         */
        async saveRedditConfig(showSuccess = true, refreshPreview = true) {
            if (!this.currentMac) return;
            try {
                const res = await fetch(`/admin/device/${this.currentMac}/settings`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ reddit_config: this.redditConfig })
                });
                if (res.ok) {
                    if (showSuccess) {
                        this.redditStatus = '<span style="color: #10b981;">✅ Config Saved</span>';
                        setTimeout(() => { this.redditStatus = 'Ready'; }, 3000);
                    }
                    await this.fetchDevices();
                    if (refreshPreview) await this.loadRedditPreview();
                }
            } catch (e) {
                console.error("Save reddit config error:", e);
            }
        },

        /**
         * Load the list of processed Reddit posts (preview).
         */
        async loadRedditPreview() {
            if (!this.currentMac) return;
            try {
                const res = await fetch(`/admin/reddit/preview/${this.currentMac}`);
                const data = await res.json();
                this.redditPreview = data.posts || [];
            } catch (e) {
                console.error("Load reddit preview error:", e);
            }
        },

        /**
         * Trigger an immediate fetch of Reddit RSS content.
         * Polls the server for progress updates.
         */
        async fetchRedditNow() {
            this.isFetchingReddit = true;
            this.redditStatus = '⏳ Saving & Fetching...';
            
            try {
                await this.saveRedditConfig(false, false);
                
                const res = await fetch(`/admin/reddit/fetch_now/${this.currentMac}`, { method: 'POST' });
                if (res.ok) {
                    this.redditStatus = '<span style="color: #fbbf24;">⏳ Fetch triggered...</span>';
                    
                    const poll = setInterval(async () => {
                        const r = await fetch(`/admin/reddit/preview/${this.currentMac}`);
                        const d = await r.json();
                        
                        if (d.status === 'fetching') {
                            this.redditStatus = `<span style="color: #fbbf24;">⏳ Fetching: ${d.progress || 'Processing...'}</span>`;
                        } else {
                            clearInterval(poll);
                            this.isFetchingReddit = false;
                            this.redditStatus = '<span style="color: #10b981;">✅ Fetch Complete!</span>';
                            await this.loadRedditPreview();
                            setTimeout(() => { this.redditStatus = 'Ready'; }, 5000);
                        }
                    }, 2000);
                } else {
                    this.redditStatus = '<span style="color: #ef4444;">❌ Failed to trigger fetch.</span>';
                    this.isFetchingReddit = false;
                }
            } catch (e) {
                this.redditStatus = `<span style="color: #ef4444;">❌ Error: ${e}</span>`;
                this.isFetchingReddit = false;
            }
        },

        /**
         * Handle subreddit name changes.
         * Title inclusion logic is now fully AI-driven.
         */
        handleRedditSubChange() {
            // AI now decides title inclusion automatically.
            // Subreddit-specific logic for title toggling is removed.
        },

        /**
         * Set the bit depth for Reddit image processing and apply presets if AI is off.
         */
        setRedditBitDepth(depth) {
            this.redditConfig.bit_depth = parseInt(depth);
            if (!this.redditConfig.auto_optimize) {
                if (this.redditConfig.bit_depth === 2) {
                    this.redditConfig.gamma_index = 6; // 2.2
                    this.redditConfig.sharpen_amount = 0.2;
                } else {
                    this.redditConfig.gamma_index = 0; // 1.0
                    this.redditConfig.sharpen_amount = 0;
                }
            }
        },

        /**
         * Clear the Reddit cache and delete associated images for the current device.
         */
        async clearRedditCache() {
            if (!this.currentMac) return;
            if (!confirm("Are you sure you want to clear the Reddit cache and delete all processed images?")) return;
            
            try {
                const res = await fetch(`/admin/reddit/cache/${this.currentMac}`, { method: 'DELETE' });
                if (res.ok) {
                    this.redditPreview = [];
                    this.redditStatus = '<span style="color: #10b981;">🗑️ Cache Cleared</span>';
                    setTimeout(() => { this.redditStatus = 'Ready'; }, 3000);
                }
            } catch (e) {
                console.error("Clear reddit cache error:", e);
            }
        }
    }));
});
