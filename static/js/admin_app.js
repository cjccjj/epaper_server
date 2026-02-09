/**
 * admin_app.js
 * Alpine.js state management for the E-Paper Server Admin UI.
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('adminApp', () => ({
        // --- State ---
        devices: [],
        currentMac: localStorage.getItem('lastSelectedMac') || '',
        activeDish: 'gallery',
        currentTab: localStorage.getItem('lastSelectedTab') || 'gallery',
        
        // Device Settings (bound to UI)
        deviceSettings: {
            name: '',
            refresh_rate: 30,
            display_width: 400,
            display_height: 300,
            timezone: 'UTC'
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
        
        // Reddit State
        redditConfig: {
            subreddit: '',
            show_title: true,
            bit_depth: 2,
            gamma_index: 6,
            clip_percent: 20,
            cost_percent: 6,
            sharpen_amount: 0.2,
            dither_strength: 1.0,
            auto_optimize: true
        },
        redditPreview: [],
        redditStatus: 'Ready',
        isFetchingReddit: false,
        
        // UI Helpers
        isAnalyzingAI: false,
        aiInfo: '',
        gammaLabels: [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4],

        // --- Init ---
        async init() {
            this.img = new Image();
            this.img.onload = () => this.processImage();
            this.img.onerror = () => {
                if (this.img.src && !this.img.src.startsWith('data:image/png;base64,iVBOR')) {
                    alert("Failed to load image.");
                }
            };

            await this.fetchDevices();
            
            // Restore last state
            if (this.currentMac) {
                await this.selectDevice(this.currentMac);
            }
            
            this.showTab(this.currentTab);

            // Global click handler for overlay
            window.addEventListener('click', (e) => {
                if (e.target.id === 'overlay') {
                    e.target.style.display = 'none';
                }
            });
        },

        // --- Device Management ---
        async fetchDevices() {
            try {
                const res = await fetch('/admin/devices');
                this.devices = await res.json();
            } catch (e) {
                console.error("Failed to fetch devices:", e);
            }
        },

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

        async saveDeviceSettings() {
            if (!this.currentMac) return;
            try {
                await fetch(`/admin/device/${this.currentMac}/settings`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(this.deviceSettings)
                });
                await this.fetchDevices(); // Refresh list
            } catch (e) {
                console.error("Failed to save settings:", e);
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

        // --- Tab Management ---
        async showTab(tab) {
            this.currentTab = tab;
            localStorage.setItem('lastSelectedTab', tab);
            
            if (tab === 'reddit' && this.currentMac) {
                await this.loadRedditConfig();
            }
        },

        // --- Gallery Management ---
        async loadGallery() {
            if (!this.currentMac) return;
            try {
                const res = await fetch(`/admin/gallery/${this.currentMac}`);
                this.galleryItems = await res.json();
            } catch (e) {
                console.error("Failed to load gallery:", e);
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
                clipPct: this.galleryConfig.clip / 100,
                costPct: this.galleryConfig.cost / 100,
                gamma: this.gammaLabels[this.galleryConfig.gamma],
                sharpen: parseFloat(this.galleryConfig.sharpen),
                ditherStrength: this.galleryConfig.ditherStrength / 100
            };

            const result = ImageProcess.process(this.img, canvases, options);
            this.stats = `Range: ${result.left} - ${result.right}`;
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
                    this.galleryConfig.bitDepth = 'fs'; // Default to BW for AI optimization as per original code
                    
                    const applied = `sh:${Math.round(sh*100)}% dt:${Math.round(dt*100)}% gm:${this.gammaLabels[gmIndex].toFixed(1)}`;
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

            const bitDepth = this.galleryConfig.bitDepth;
            const pngData = ImageProcess.canvasToPNG(canvas, bitDepth);
            
            const blob = new Blob([pngData], { type: 'image/png' });
            const fd = new FormData();
            fd.append('file', blob, 'image.png');
            
            try {
                const res = await fetch(`/admin/gallery/${this.currentMac}/upload`, {
                    method: 'POST',
                    body: fd
                });
                if (res.ok) {
                    await this.loadGallery();
                    alert("Uploaded successfully!");
                } else {
                    alert("Upload failed.");
                }
            } catch (e) {
                console.error("Upload error:", e);
                alert("Upload error.");
            }
        },

        async deleteImage(filename) {
            if (!confirm("Delete this image?")) return;
            try {
                const res = await fetch(`/admin/gallery/${this.currentMac}/delete/${filename}`, { method: 'DELETE' });
                if (res.ok) await this.loadGallery();
            } catch (e) {
                console.error("Delete error:", e);
            }
        },

        async setAsActive(filename) {
            try {
                const res = await fetch(`/admin/gallery/${this.currentMac}/set_active/${filename}`, { method: 'POST' });
                if (res.ok) await this.loadGallery();
            } catch (e) {
                console.error("Set active error:", e);
            }
        },

        showOverlay(url) {
            const overlay = document.getElementById('overlay');
            const overlayImg = document.getElementById('overlayImg');
            overlayImg.src = url;
            overlay.style.display = 'flex';
        },

        // --- Reddit Management ---
        async loadRedditConfig() {
            if (!this.currentMac) return;
            try {
                const res = await fetch(`/admin/reddit/config/${this.currentMac}`);
                const config = await res.json();
                if (config) {
                    this.redditConfig = config;
                }
                await this.loadRedditPreview();
            } catch (e) {
                console.error("Failed to load reddit config:", e);
            }
        },

        async saveRedditConfig(showSuccess = true, refreshPreview = true) {
            if (!this.currentMac) return;
            try {
                const res = await fetch(`/admin/reddit/config/${this.currentMac}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(this.redditConfig)
                });
                if (res.ok) {
                    if (showSuccess) {
                        this.redditStatus = '<span style="color: #10b981;">✅ Config Saved</span>';
                        setTimeout(() => { this.redditStatus = 'Ready'; }, 3000);
                    }
                    if (refreshPreview) await this.loadRedditPreview();
                }
            } catch (e) {
                console.error("Save reddit config error:", e);
            }
        },

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

        handleRedditSubChange() {
            const memes = ['memes', 'dankmemes', 'AdviceAnimals', 'wholesomememes', 'PrequelMemes', 'HistoryMemes', 'trippinthroughtime', 'me_irl', 'Antimeme', 'StarterPacks'];
            this.redditConfig.show_title = !memes.includes(this.redditConfig.subreddit);
        },

        setRedditBitDepth(depth) {
            this.redditConfig.bit_depth = parseInt(depth);
            if (this.redditConfig.bit_depth === 2) {
                this.redditConfig.gamma_index = 6; // 2.2
                this.redditConfig.clip_percent = 20;
                this.redditConfig.cost_percent = 6;
                this.redditConfig.sharpen_amount = 0.2;
            } else {
                this.redditConfig.gamma_index = 0; // 1.0
                this.redditConfig.clip_percent = 22;
                this.redditConfig.cost_percent = 6;
                this.redditConfig.sharpen_amount = 0;
            }
        }
    }));
});
