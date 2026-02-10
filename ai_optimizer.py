import os
import json
import base64
import asyncio
from io import BytesIO
from openai import OpenAI
from pydantic import BaseModel
from typing import Literal

# Initialize OpenAI client
client = OpenAI()

# --- Thresholds & Constraints ---
# These define when we skip images or choose specific resize methods
CROP_THRESHOLD = 0.5    # Max 20% crop allowed
STRETCH_THRESHOLD = 0.3  # Max 30% distortion allowed
PAD_THRESHOLD = 0.5     # Max 35% padding allowed before skipping

class ImageRenderIntent(BaseModel):
    # 1. Classification (Step 0 in prompt)
    image_style: Literal[
        "photography", "screenshot", "meme", "illustration", "comic", "diagram", "mixed"
    ]
    post_purpose: Literal[
        "humor", "informational", "artistic", "showcase", "social", "reaction", "others"
    ]

    # 2. Decision
    decision: Literal["use", "skip"]

    # 3. Resize Strategy (Step 2 in prompt)
    resize_strategy: Literal["stretch", "crop", "pad_white", "pad_black"]

    # 4. Processing Parameters (Steps 3, 4, 5 in prompt)
    gamma: float   # 1.0 - 2.4
    sharpen: float # 0.0 - 2.0
    dither: int    # 0 - 100

    # 5. Title Overlay (Step 6 in prompt)
    include_title: bool

DEFAULT_SYSTEM_PROMPT = """
You are an e‑paper image optimization assistant.

Target display:
- Small 4.2‑inch, 400×300, 2‑bit grayscale e‑paper screen (4 gray levels)
- Limited contrast

Your task:
Analyze the image content, visible text inside the image, the Post Title, and the Post URL.
Determine how the image should be processed to maximize readability and meaning on the target display.

You must think like a human viewer reading this on a small e‑paper screen.

────────────────────────
IMAGE CLASSIFICATION
────────────────────────

Image STYLE:
- Real‑World Photography
- Screenshots / Digital Captures
- Memes / Image Macros
- Illustration / Digital Art
- Comics / Cartoons / Line Art
- Data / Diagrams / Infographics
- Mixed / others

POST PURPOSE:
- Humor
- Informational
- Artistic
- Showcase
- Social (tweets, conversations)
- Reaction
- Others

Text inside image:
- Overlay text above, below, or on the image is usually critical and must be preserved
- Small watermarks or footers do NOT count as important text

Image STYLE + POST PURPOSE together determine what must survive on a small grayscale display and how aggressively the image can be processed.

────────────────────────
DECISION STEPS
────────────────────────

0. Classification
Use IMAGE CLASSIFICATION as guidance for analysis.
Include ONE Image STYLE and ONE POST PURPOSE in the output for debug purpose.

1. Use or Skip the Image
Skip the image if ANY of the following apply:
- Too wide or too tall aspect ratio
- Contains a large amount of tiny text (more than ~50 words)
- Information density is too high to be readable on a small screen

2. Resize Strategy
Target is to maximize screen usage.

Choose ONE:
- Stretch: For humor or casual images, even with text inside, stretching increases readability.
- Crop: For artistic images, crop unless the main subject extends to the edge. For images with text inside, avoid cropping.
- Fit with padding: Keep aspect ratio; use when stretch or crop is unsafe.

If padding is used:
- Choose background color: black or white
- If uncertain, choose white

3. Gamma Correction (range: 1.0 – 2.4)
Purpose: recover shadow detail lost on 2‑bit grayscale displays.

Guidelines:
- 1.0 = no correction
- Higher values brighten shadows but reduce highlight detail
- Real‑world photography: usually ≤ 1.4
- Comics, charts, line art, UI screenshots: can be higher
- Images with rich shadows benefit more from gamma correction

4. Sharpening (range: 0.0 – 2.0)
Purpose: enhance edges and text clarity (not tonal contrast).

Guidelines:
- Real‑world photography: usually ≤ 0.4
- Text‑centric images, flat color comics, diagrams, line art: 1.0 – 2.0
- Mixed content: 0.4 – 1.0, choose a balanced value

5. Dithering (range: 0 – 100)
Purpose: simulate gradients on a 4‑level grayscale display.

Guidelines:
- High to mid gradient color‑rich content (photos without text, realism paintings): 80 – 100
- Mid to low gradient content (photo with text, paintings, drawings): 50 – 80
- No gradient content (flat color comics, diagrams, UI, line art): 0 – 40
- Lower dithering preserves stronger tonal contrast but loses details

6. Add Post Title Overlay (If Needed)
Purpose: decide whether to place the Post Title near the bottom of the image for clarity.

Guidelines:
- Do not add if the image already contains text
- Do not add if the image is self‑explanatory
- Add if the image alone is unclear and the Post Title adds meaningful context

────────────────────────
OUTPUT RULES
────────────────────────

- Return ONLY values allowed by the output schema
- Do NOT explain reasoning
"""

def analyze_image(image_input, post_title="", post_url="", target_resolution=(400, 300), custom_prompt=None) -> ImageRenderIntent:
    """
    Analyzes an image (URL or PIL Image) using OpenAI Vision and returns a structured style object.
    Use custom_prompt from the caller (database). 
    If absolutely none provided, it will fail or use a very minimal fallback to avoid crash.
    """
    if not custom_prompt:
        # If we reach here without a prompt, it's a dev error or manual call without config.
        # We use the DEFAULT_SYSTEM_PROMPT as a last resort, but the goal is to always pass one.
        system_prompt = DEFAULT_SYSTEM_PROMPT
    else:
        system_prompt = custom_prompt
    
    # Handle image input
    if isinstance(image_input, str):
        # It's a URL (Reddit use case)
        image_url_str = image_input
    else:
        # It's a PIL Image (Gallery AI use case), convert to base64
        buffered = BytesIO()
        image_input.save(buffered, format="JPEG", quality=85)
        base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
        image_url_str = f"data:image/jpeg;base64,{base64_image}"

    user_content = [
        {"type": "text", "text": f"Analyze this image for e-paper optimization.\nPost Title: {post_title}\nPost URL: {post_url}\nTarget Resolution: {target_resolution[0]}x{target_resolution[1]}"},
        {
            "type": "image_url",
            "image_url": {"url": image_url_str, "detail": "low"}
        },
    ]

    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-5-mini", # Switch to gpt-5-mini as requested
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format=ImageRenderIntent,
        )
        return completion.choices[0].message.parsed
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        # Return a skip intent if AI fails
        return ImageRenderIntent(
            image_style="mixed",
            post_purpose="others",
            decision="skip",
            resize_strategy="pad_white",
            gamma=1.0,
            sharpen=0.0,
            dither=0,
            include_title=False
        )

async def get_ai_analysis(img_url, post_url, post_title, target_resolution, ai_prompt=None):
    """
    AI Interface: Analyzes image and post metadata using real AI.
    Now includes aspect ratio filtering before calling AI.
    """
    try:
        # Step 1: Download image to check aspect ratio
        import image_processor
        img_ori = await asyncio.to_thread(image_processor.download_image_simple, img_url)
        if not img_ori:
            return {"decision": "skip", "reason": "Download failed"}
            
        # Step 2: Check side length and aspect ratio
        width, height = img_ori.size
        
        tw, th = target_resolution
        
        # Relative side length filter: skip if < 50% of target width or height
        if width < tw * 0.5 or height < th * 0.5:
            return {"decision": "skip", "reason": f"Image too small ({width}x{height} < 50% of {tw}x{th})"}

        ratio = width / height
        target_ar = tw / th
        
        # Ratio filter: choose max from thresholds to use as the filter limit
        MAX_THRESHOLD = max(CROP_THRESHOLD, STRETCH_THRESHOLD, PAD_THRESHOLD)
        
        # Calculate limits based on the maximum allowed threshold
        max_ar = target_ar / (1 - MAX_THRESHOLD)
        min_ar = target_ar * (1 - MAX_THRESHOLD)
        
        if ratio > max_ar:
            return {"decision": "skip", "reason": f"Image too wide (ratio {ratio:.2f} > {max_ar:.2f})"}
        if ratio < min_ar:
            return {"decision": "skip", "reason": f"Image too narrow (ratio {ratio:.2f} < {min_ar:.2f})"}

        # Step 3: Analyze with AI
        style_obj = await asyncio.to_thread(
            analyze_image,
            img_url, 
            post_title=post_title, 
            post_url=post_url, 
            target_resolution=target_resolution,
            custom_prompt=ai_prompt
        )
        if style_obj.decision == "skip":
             return {"decision": "skip", "reason": "AI Decision: Skip"}
             
        return {
            "image_style": style_obj.image_style,
            "post_purpose": style_obj.post_purpose,
            "decision": style_obj.decision,
            "resize_strategy": style_obj.resize_strategy,
            "gamma": style_obj.gamma,
            "sharpen": style_obj.sharpen,
            "dither": style_obj.dither,
            "include_title": style_obj.include_title,
            "_img_size": (width, height)
        }
    except Exception as e:
        print(f"Error in get_ai_analysis for {post_title}: {e}")
        return {"decision": "skip", "reason": f"AI Error: {str(e)}"}

def get_process_strategy(ai_output, img_size=None, target_res=None):
    """
    Process Strategy Interface: Converts AI analysis into technical parameters.
    Input: 
        ai_output (dict): Output from get_ai_analysis (ImageRenderIntent schema)
        img_size (tuple): (width, height) of original image
        target_res (tuple): (width, height) of target display
    Output:
        dict: Technical processing parameters
    """
    # 1. Decision from AI
    if not ai_output:
        return {"decision": "skip", "reason": "No AI output"}
        
    if ai_output.get("decision") == "skip":
        return {"decision": "skip", "reason": ai_output.get("reason", "AI Decision: Skip")}
    
    # Default values for processing (used if AI values out of range)
    DEFAULT_GAMMA = 1.0
    DEFAULT_SHARPEN = 0.5
    DEFAULT_DITHER = 50

    gamma = ai_output.get("gamma", DEFAULT_GAMMA)
    sharpen = ai_output.get("sharpen", DEFAULT_SHARPEN)
    dither_val = ai_output.get("dither", DEFAULT_DITHER)

    # Range checks - use defaults if out of range
    if not (1.0 <= gamma <= 2.4): 
        gamma = DEFAULT_GAMMA
    if not (0.0 <= sharpen <= 2.0): 
        sharpen = DEFAULT_SHARPEN
    if not (0 <= dither_val <= 100): 
        dither_val = DEFAULT_DITHER
    
    dither_strength = dither_val / 100.0

    strategy = ai_output.get("resize_strategy", "pad_white")
    final_method = "padding"
    padding_color = "white"

    # If we have image size, we check thresholds for crop/stretch/pad
    if img_size and target_res:
        w, h = img_size
        tw, th = target_res
        img_ar = w / h
        target_ar = tw / th

        if strategy == "crop":
            # Calculate how much we need to crop
            if img_ar > target_ar: # Wider than target, crop width
                crop_amt = (w - h * target_ar) / w
            else: # Taller than target, crop height
                crop_amt = (h - w / target_ar) / h
            
            if crop_amt <= CROP_THRESHOLD:
                final_method = "crop"
            else:
                return {"decision": "skip", "reason": f"Crop limit exceeded ({crop_amt:.1%})"}

        elif strategy == "stretch":
            # Calculate distortion
            stretch_amt = abs(img_ar / target_ar - 1)
            if stretch_amt <= STRETCH_THRESHOLD:
                final_method = "stretch"
            else:
                return {"decision": "skip", "reason": f"Stretch limit exceeded ({stretch_amt:.1%})"}
        
        elif strategy.startswith("pad"):
            # Calculate padding amount
            if img_ar > target_ar: # Image wider, pad top/bottom
                pad_amt = (th - (tw / img_ar)) / th
            else: # Image taller, pad sides
                pad_amt = (tw - (th * img_ar)) / tw
            
            if pad_amt <= PAD_THRESHOLD:
                final_method = "padding"
                padding_color = "black" if strategy == "pad_black" else "white"
            else:
                return {"decision": "skip", "reason": f"Padding limit exceeded ({pad_amt:.1%})"}
    else:
        # No image size yet (shouldn't happen with new flow), fallback to pad
        if strategy == "stretch": final_method = "stretch"
        elif strategy == "crop": final_method = "crop"
        elif strategy == "pad_black": padding_color = "black"
        else: padding_color = "white"

    return {
        "decision": "use",
        "image_style": ai_output.get("image_style"),
        "post_purpose": ai_output.get("post_purpose"),
        "resize_method": final_method,
        "padding_color": padding_color,
        "gamma": gamma,
        "sharpen": sharpen,
        "dither_strength": dither_strength,
        "include_title": ai_output.get("include_title", False)
    }
