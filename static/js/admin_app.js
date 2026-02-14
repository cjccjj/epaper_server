/**
 * admin_app.js
 * Alpine.js state management for the E-Paper Server Admin UI.
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('adminApp', () => ({
        // --- State ---
        devices: [],
        currentMac: '', // Initialize empty, will restore in init
        activeDish: 'gallery',
        currentTab: localStorage.getItem('lastSelectedTab') || 'gallery',
        baseUrl: '',
        
        // Device Settings (bound to UI)
        deviceSettings: {
            name: '',
            refresh_rate: 30,
            display_width: 400,
            display_height: 300,
            timezone: 'UTC',
            enabled_dishes: ['gallery'],
            display_mode: 'sequence'
        },
        
        // Gallery State
        img: null, // Will hold the Image object
        galleryItems: [],
        galleryConfig: {
            bitDepth: 'fs4g',
            clip: 22,
            cost: 6,
            gamma: 0, // Index into [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]
            sharpen: 0.1,
            ditherStrength: 100
        },
        stats: '',
        
        // RSS State
        rssSources: [],
        currentRssSourceId: null,
        rssConfig: {
    url: '',
    name: '',
    bit_depth: 2,
    auto_optimize: true,
    gamma_index: 0,
    sharpen_amount: 0.1,
    dither_strength: 1.0,
    clip_percent: 22,
    cost_percent: 6,
    ai_prompt: ''
},
        rssPreview: [],
        rssStatus: 'Ready',
        isFetchingRss: false,
        
        // UI Helpers
        isAnalyzingAI: false,
                isUploading: false,
                aiInfo: '',
        gammaLabels: [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4],

        // --- Init ---
        async init() {
            // 1. Basic Setup
            this.img = new Image();
            this.img.onload = () => this.processImage();
            this.img.onerror = () => {
                if (this.img.src && !this.img.src.startsWith('data:image/png;base64,iVBOR')) {
                    alert("Failed to load image.");
                }
            };

            // 2. Fetch Data
            await Promise.all([
                this.fetchDevices(),
                this.fetchConfig()
            ]);
            
            // 3. Restore Selection
            const savedMac = localStorage.getItem('lastSelectedMac');
            if (savedMac && this.devices.some(d => d.mac_address === savedMac)) {
                this.currentMac = savedMac;
            } else if (this.devices.length > 0) {
                this.currentMac = this.devices[0].mac_address;
            }
            
            // 4. Initial Load
            if (this.currentMac) {
                await this.selectDevice(this.currentMac);
            }
            this.showTab(this.currentTab);

            // Global click handler for overlay
            window.addEventListener('click', (e) => {
                if (e.target.id === 'overlay') e.target.style.display = 'none';
            });
        },

        // --- Device Management ---
        async fetchDevices() {
            try {
                const res = await fetch('/admin/devices');
                this.devices = await res.json();
                console.log("Fetched devices:", this.devices);
            } catch (e) {
                console.error("Failed to fetch devices:", e);
            }
        },

        async fetchConfig() {
            try {
                const res = await fetch('/api/config');
                const config = await res.json();
                this.baseUrl = config.base_url || '';
            } catch (e) {
                console.error("Failed to fetch server config:", e);
            }
        },

        async selectDevice(mac) {
            this.currentMac = mac;
            localStorage.setItem('lastSelectedMac', mac);
            
            const device = this.devices.find(d => d.mac_address === mac);
            if (!device) return;

            // Update local settings from device object
            this.deviceSettings = {
                friendly_id: device.friendly_id,
                refresh_rate: device.refresh_rate,
                display_width: device.display_width,
                display_height: device.display_height,
                timezone: device.timezone,
                enabled_dishes: device.enabled_dishes || ['gallery'],
                display_mode: device.display_mode || 'sequence',
                active_dish: device.active_dish,
                last_served_image: device.last_served_image
            };
            this.galleryItems = device.images || [];
            this.rssSources = device.rss_sources || [];
            
            // Set current RSS source for preview if none selected
            if (!this.currentRssSourceId && this.rssSources.length > 0) {
                this.selectRssSource(this.rssSources[0].id);
            } else if (this.rssSources.length === 0) {
                this.currentRssSourceId = null;
                this.rssPreview = [];
            }
            
            // Centralized config loading based on current state
            await this.refreshCurrentTab();

            // Also update the activeDish local state to match device
            this.activeDish = device.active_dish || 'gallery';
        },

        async refreshCurrentTab() {
            if (!this.currentMac) return;
            
            if (this.currentTab === 'gallery') await this.loadGallery();
            else if (this.currentTab === 'rss') await this.loadRssPreview();
        },

        async showTab(tab) {
            this.currentTab = tab;
            localStorage.setItem('lastSelectedTab', tab);
            await this.refreshCurrentTab();
        },

        async saveDeviceSettings() {
            if (!this.currentMac) return;
            try {
                const payload = { ...this.deviceSettings };
                await fetch(`/admin/device/${this.currentMac}/settings`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                await this.fetchDevices(); // Refresh list
            } catch (e) {
                console.error("Failed to save settings:", e);
            }
        },

        selectRssSource(id) {
            this.currentRssSourceId = id;
            const s = this.rssSources.find(src => src.id === id);
            if (s) {
                this.rssConfig = { ...this.rssConfig, ...s.config, url: s.url, name: s.name };
                this.loadRssPreview();
            }
        },

        async addRssSource() {
            if (!this.rssConfig.url) return alert("Please enter an RSS URL.");
            try {
                const res = await fetch(`/admin/rss/add/${this.currentMac}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: this.rssConfig.url,
                        name: this.rssConfig.name,
                        config: { ...this.rssConfig }
                    })
                });
                const d = await res.json();
                if (res.ok) {
                    await this.fetchDevices();
                    this.selectRssSource(d.source_id);
                    
                    // Auto-enable if not in enabled_dishes
                    const dishKey = `rss_${d.source_id}`;
                    if (!this.deviceSettings.enabled_dishes.includes(dishKey)) {
                        this.deviceSettings.enabled_dishes.push(dishKey);
                        await this.saveDeviceSettings();
                    }
                } else {
                    alert(d.detail || "Failed to add RSS source.");
                }
            } catch (e) {
                console.error("Add RSS error:", e);
            }
        },

        async deleteRssSource(id) {
            if (!confirm("Are you sure you want to delete this RSS source?")) return;
            try {
                const res = await fetch(`/admin/rss/delete/${this.currentMac}/${id}`, { method: 'POST' });
                if (res.ok) {
                    if (this.currentRssSourceId === id) this.currentRssSourceId = null;
                    await this.fetchDevices();
                }
            } catch (e) {
                console.error("Delete RSS error:", e);
            }
        },

        async setActiveDish(dish) {
            this.activeDish = dish;
            await fetch(`/admin/device/${this.currentMac}/settings`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ active_dish: dish })
            });
            // Update local device object too
            const d = this.devices.find(x => x.mac_address === this.currentMac);
            if (d) d.active_dish = dish;
        },

        async toggleDish(dish) {
            if (!this.deviceSettings.enabled_dishes) {
                this.deviceSettings.enabled_dishes = ['gallery'];
            }
            
            const isEnabled = this.deviceSettings.enabled_dishes.includes(dish);
            const isActive = this.deviceSettings.active_dish === dish;

            if (!isEnabled) {
                // 1. Not enabled -> enable it
                this.deviceSettings.enabled_dishes.push(dish);
            } else if (!isActive) {
                // 2. Enabled but not active -> make it active
                this.deviceSettings.active_dish = dish;
            } else {
                // 3. Enabled and active -> disable it (unless it's the only one)
                if (this.deviceSettings.enabled_dishes.length > 1) {
                    const index = this.deviceSettings.enabled_dishes.indexOf(dish);
                    this.deviceSettings.enabled_dishes.splice(index, 1);
                    // If we just disabled the active dish, pick another one to be active
                    if (this.deviceSettings.active_dish === dish) {
                        this.deviceSettings.active_dish = this.deviceSettings.enabled_dishes[0];
                    }
                } else {
                    alert("At least one source must be enabled.");
                    return;
                }
            }
            
            await this.saveDeviceSettings();
        },

        // --- Gallery Management ---
        async loadGallery() {
            if (!this.currentMac) return;
            const device = this.devices.find(d => d.mac_address === this.currentMac);
            if (device) {
                this.galleryItems = device.images || [];
            }
        },

        handleFileUpload(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            const reader = new FileReader();
            reader.onload = (ev) => {
                this.img.src = ev.target.result;
            };
            reader.readAsDataURL(file);
        },

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
 
            const result = ImageProcess.process(this.img, canvases, options);
        },

        async aiOptimize() {
            if (!this.img || !this.img.src) {
                alert("Please select an image first.");
                return;
            }

            this.isAnalyzingAI = true;
            this.aiInfo = "AI is analyzing image...";
            
            try {
                // Use a temporary canvas to resize for AI analysis
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
                    let sh = 0.2;
                    if (style.has_text_overlay || style.content_type === "text_heavy") sh = 1.0;
                    else if (style.content_type === "comic_illustration") sh = 0.5;
                    
                    let dt = 1.0;
                    if (style.gradient_complexity === "low") dt = 0.4;
                    
                    let gmIndex = (style.content_type === "comic_illustration") ? 6 : 0; // 6=2.2, 0=1.0

                    // Update config
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
                    // Successfully uploaded
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


        showOverlay(url) {
            const overlay = document.getElementById('overlay');
            const overlayImg = document.getElementById('overlayImg');
            overlayImg.src = url;
            overlay.style.display = 'flex';
        },

        // --- RSS Management ---

        async loadRssPreview() {
            if (!this.currentMac || !this.currentRssSourceId) {
                this.rssPreview = [];
                return;
            }
            try {
                const res = await fetch(`/admin/rss/preview/${this.currentMac}/${this.currentRssSourceId}`);
                const data = await res.json();
                this.rssPreview = data.posts || [];
            } catch (e) {
                console.error("Load RSS preview error:", e);
            }
        },

        async saveRssConfig() {
            await this.addRssSource();
        },

        async fetchRssNow() {
            if (!this.currentRssSourceId) {
                alert("Please select or add an RSS source first.");
                return;
            }
            this.isFetchingRss = true;
            this.rssStatus = '⏳ Saving & Fetching...';
            
            try {
                // First save the config (updates name/url/config)
                await this.saveRssConfig();

                const res = await fetch(`/admin/rss/fetch_now/${this.currentMac}/${this.currentRssSourceId}`, { method: 'POST' });
                if (res.ok) {
                    this.rssStatus = '<span style="color: #fbbf24;">⏳ Fetch triggered...</span>';
                    
                    const poll = setInterval(async () => {
                        const r = await fetch(`/admin/rss/preview/${this.currentMac}/${this.currentRssSourceId}`);
                        const d = await r.json();
                        
                        if (d.posts && Array.isArray(d.posts)) {
                            this.rssPreview = d.posts;
                        }

                        if (d.status === 'fetching') {
                            this.rssStatus = `<span style="color: #fbbf24;">⏳ Fetching: ${d.progress || 'Processing...'}</span>`;
                        } else {
                            clearInterval(poll);
                            this.isFetchingRss = false;
                            this.rssStatus = '<span style="color: #10b981;">✅ Fetch Complete!</span>';
                            await this.loadRssPreview();
                            setTimeout(() => { this.rssStatus = 'Ready'; }, 5000);
                        }
                    }, 2000);
                } else {
                    this.rssStatus = '<span style="color: #ef4444;">❌ Failed to trigger fetch.</span>';
                    this.isFetchingRss = false;
                }
            } catch (e) {
                console.error("Fetch RSS error:", e);
                this.rssStatus = `<span style="color: #ef4444;">❌ Error: ${e}</span>`;
                this.isFetchingRss = false;
            }
        }
    }));
});
