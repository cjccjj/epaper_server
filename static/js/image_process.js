/**
 * Image Processing Module for E-Paper Server
 * Handles grayscale conversion, sharpening, gamma correction, auto-contrast, and dithering.
 */

const ImageProcess = {
    /**
     * Converts RGB ImageData to Grayscale
     */
    grayscale(data) {
        for (let i = 0; i < data.length; i += 4) {
            const g = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
            data[i] = data[i + 1] = data[i + 2] = g;
            data[i + 3] = 255;
        }
    },

    /**
     * Applies Laplacian sharpening (3x3 kernel)
     */
    sharpen(data, width, height, amount) {
        if (amount <= 0) return;
        const copy = new Uint8ClampedArray(data);
        for (let y = 1; y < height - 1; y++) {
            for (let x = 1; x < width - 1; x++) {
                const i = (y * width + x) * 4;
                const center = copy[i];
                const up = copy[((y - 1) * width + x) * 4];
                const down = copy[((y + 1) * width + x) * 4];
                const left = copy[(y * width + (x - 1)) * 4];
                const right = copy[(y * width + (x + 1)) * 4];
                const sharpened = center + (center * 4 - up - down - left - right) * amount;
                data[i] = data[i + 1] = data[i + 2] = Math.max(0, Math.min(255, sharpened));
            }
        }
    },

    /**
     * Applies Gamma correction
     */
    gammaCorrection(data, gamma) {
        if (gamma === 1.0) return;
        for (let i = 0; i < data.length; i += 4) {
            const g = 255 * Math.pow(data[i] / 255, 1 / gamma);
            data[i] = data[i + 1] = data[i + 2] = g;
        }
    },

    /**
     * Weighted Approaching Auto-Contrast (W-Approaching)
     */
    autoContrast(data, width, height, clipPct, costPct) {
        const hist = new Array(256).fill(0);
        let sumValues = 0;
        const total = width * height;

        for (let i = 0; i < data.length; i += 4) {
            const v = data[i] | 0;
            hist[v]++;
            sumValues += v;
        }

        const avg = sumValues / (total || 1);
        let totalPotentialDamage = 0;
        for (let i = 0; i < 256; i++) {
            totalPotentialDamage += hist[i] * Math.abs(i - avg);
        }

        const targetArea = total * clipPct;
        const targetCost = totalPotentialDamage * costPct;
        const minTarget = total * 0.002; // 0.2% safety clip

        let left = 0, right = 255;
        let clippedTotal = 0, totalCost = 0;
        let clippedL = 0, clippedR = 0;

        // Safety clip first
        while (left < right && clippedL < minTarget) { clippedL += hist[left]; left++; }
        while (left < right && clippedR < minTarget) { clippedR += hist[right]; right--; }

        // Weighted approaching
        while (left < right && totalCost < targetCost && clippedTotal < targetArea) {
            const costL = hist[left] * left;
            const costR = hist[right] * (255 - right);

            if (costL <= costR) {
                if (totalCost + costL > targetCost) break;
                totalCost += costL;
                clippedTotal += hist[left];
                left++;
            } else {
                if (totalCost + costR > targetCost) break;
                totalCost += costR;
                clippedTotal += hist[right];
                right--;
            }
        }

        const acScale = 255 / (right - left || 1);
        for (let i = 0; i < data.length; i += 4) {
            let v = data[i];
            if (v <= left) v = 0;
            else if (v >= right) v = 255;
            else v = (v - left) * acScale;
            data[i] = data[i + 1] = data[i + 2] = Math.max(0, Math.min(255, v));
        }

        return { left, right };
    },

    /**
     * Floyd-Steinberg Dithering
     * levels: 2 for BW, 4 for Grayscale
     */
    dither(data, width, height, levels, strength) {
        const ditherData = data; // Operates in-place on the passed Uint8ClampedArray
        const step = 255 / (levels - 1);

        for (let y = 0; y < height; y++) {
            const ltr = y % 2 === 0;
            for (let x = ltr ? 0 : width - 1; ltr ? x < width : x >= 0; ltr ? x++ : x--) {
                const i = (y * width + x) * 4;
                const old = ditherData[i];
                const nw_val = Math.round(old / step) * step;
                const err = (old - nw_val) * strength;
                ditherData[i] = ditherData[i + 1] = ditherData[i + 2] = nw_val;

                const add = (nx, ny, f) => {
                    if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
                        const j = (ny * width + nx) * 4;
                        const v = ditherData[j] + err * f;
                        ditherData[j] = ditherData[j + 1] = ditherData[j + 2] = Math.max(0, Math.min(255, v));
                    }
                };

                if (ltr) {
                    add(x + 1, y, 7 / 16);
                    add(x - 1, y + 1, 3 / 16);
                    add(x, y + 1, 5 / 16);
                    add(x + 1, y + 1, 1 / 16);
                } else {
                    add(x - 1, y, 7 / 16);
                    add(x + 1, y + 1, 3 / 16);
                    add(x, y + 1, 5 / 16);
                    add(x - 1, y + 1, 1 / 16);
                }
            }
        }
    },

    /**
     * Main processing entry point
     */
    process(img, canvases, options) {
        const { width, height, clipPct, costPct, sharpen, gamma, bitDepth, ditherStrength } = options;
        const { original: cOriginal, dithered: cDither } = canvases;

        const gOri = cOriginal.getContext('2d', { willReadFrequently: true });
        const gDit = cDither.getContext('2d', { willReadFrequently: true });

        // 1. Resize/Crop (Fit-to-fill)
        cOriginal.width = width;
        cOriginal.height = height;
        cDither.width = width;
        cDither.height = height;

        const scale = Math.max(width / img.width, height / img.height);
        const nw = img.width * scale;
        const nh = img.height * scale;
        const ox = (width - nw) / 2;
        const oy = (height - nh) / 2;

        gOri.drawImage(img, ox, oy, nw, nh);

        // 2. Extract ImageData and run pipeline
        const imageData = gOri.getImageData(0, 0, width, height);
        const data = imageData.data;

        this.grayscale(data);
        this.gammaCorrection(data, gamma);
        this.sharpen(data, width, height, sharpen);
        const { left, right } = this.autoContrast(data, width, height, clipPct, costPct);

        // 3. Dither on a copy
        const ditherImageData = new ImageData(new Uint8ClampedArray(data), width, height);
        const levels = bitDepth === 'fs4g' ? 4 : 2;
        this.dither(ditherImageData.data, width, height, levels, ditherStrength);

        gDit.putImageData(ditherImageData, 0, 0);

        return {
            left,
            right,
            originalSize: `${img.width}x${img.height}`,
            processedSize: `${width}x${height}`
        };
    },

    /**
     * Converts a canvas to a custom 1-bit or 2-bit indexed PNG Blob
     * Requires pako for deflate
     */
    canvasToPNG(canvas, ditherMode) {
        const width = canvas.width;
        const height = canvas.height;
        const ctx = canvas.getContext('2d');
        const imageData = ctx.getImageData(0, 0, width, height);
        const data = imageData.data;

        const isBW = (ditherMode === 'fs');
        const bitDepth = isBW ? 1 : 2;

        // 1. Prepare Palette and Indices
        let palette, indices = new Uint8Array(width * height);
        if (isBW) {
            palette = [0, 0, 0, 255, 255, 255]; // Black, White
            for (let i = 0; i < data.length; i += 4) {
                indices[i / 4] = data[i] < 128 ? 0 : 1;
            }
        } else {
            palette = [0, 0, 0, 85, 85, 85, 170, 170, 170, 255, 255, 255]; // 4G levels
            for (let i = 0; i < data.length; i += 4) {
                indices[i / 4] = Math.round(data[i] / 85);
            }
        }

        // 2. Pack data for PNG (Color Type 3, Indexed)
        // Each row must start with a filter byte (0 for none)
        const bytesPerRow = Math.ceil((width * bitDepth) / 8);
        const packedData = new Uint8Array(height * (1 + bytesPerRow));
        
        for (let y = 0; y < height; y++) {
            const rowOffset = y * (1 + bytesPerRow);
            packedData[rowOffset] = 0; // Filter byte: None
            
            const rowData = new Uint8Array(bytesPerRow);
            for (let x = 0; x < width; x++) {
                const idx = indices[y * width + x];
                if (bitDepth === 1) {
                    rowData[Math.floor(x / 8)] |= (idx << (7 - (x % 8)));
                } else {
                    rowData[Math.floor(x / 4)] |= (idx << (6 - (x % 4) * 2));
                }
            }
            packedData.set(rowData, rowOffset + 1);
        }

        // 3. Helper functions for PNG construction
        const crcTable = new Int32Array(256);
        for (let n = 0; n < 256; n++) {
            let c = n;
            for (let k = 0; k < 8; k++) {
                c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
            }
            crcTable[n] = c;
        }

        function crc32(buf) {
            let crc = -1;
            for (let i = 0; i < buf.length; i++) {
                crc = crcTable[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
            }
            return (crc ^ -1) >>> 0;
        }

        function makeChunk(type, data) {
            const len = data.length;
            const buf = new Uint8Array(12 + len);
            const view = new DataView(buf.buffer);
            view.setUint32(0, len);
            buf.set(new TextEncoder().encode(type), 4);
            buf.set(data, 8);
            const crc = crc32(buf.slice(4, 8 + len));
            view.setUint32(8 + len, crc);
            return buf;
        }

        // 4. Build PNG
        const signature = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);

        const ihdrData = new Uint8Array(13);
        const ihdrView = new DataView(ihdrData.buffer);
        ihdrView.setUint32(0, width);
        ihdrView.setUint32(4, height);
        ihdrData[8] = bitDepth;
        ihdrData[9] = 3; // Color Type 3: Indexed
        ihdrData[10] = 0; // Compression: Deflate
        ihdrData[11] = 0; // Filter: Adaptive
        ihdrData[12] = 0; // Interlace: None
        const ihdr = makeChunk('IHDR', ihdrData);

        const plte = makeChunk('PLTE', new Uint8Array(palette));

        const compressed = pako.deflate(packedData, { level: 9 });
        const idat = makeChunk('IDAT', compressed);

        const iend = makeChunk('IEND', new Uint8Array(0));

        const totalLen = signature.length + ihdr.length + plte.length + idat.length + iend.length;
        const finalBuf = new Uint8Array(totalLen);
        let offset = 0;
        [signature, ihdr, plte, idat, iend].forEach(c => {
            finalBuf.set(c, offset);
            offset += c.length;
        });

        return finalBuf;
    }
};

window.ImageProcess = ImageProcess;
