import os
import json
import base64
from io import BytesIO
from openai import OpenAI
from pydantic import BaseModel
from typing import Literal

# Initialize OpenAI client
# It will look for OPENAI_API_KEY in environment variables
client = OpenAI()

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
Use IMAGE CLASSIFICATION as guidence to help your analysis.
include ONE Image STYLE and ONE POST PURPOSE in the output for debug purpose.

1. Use or Skip the Image
Skip the image if ANY of the following apply:
- Too wide or too tall aspect ratio
- Contains a large amount of tiny text (more than ~50 words)
- Information density is too high to be readable on a small screen

2. Resize Strategy
Target is to maximize screen usage.

Choose ONE:
- Stretch: Allowed if it does not distort meaning or readability; helpful for humor or casual images
- Crop: Crop unnecessary empty space or wide borders. High confidence only; never remove important subjects or text
- Fit with padding: Keep aspect ratio; use when stretch or crop is unsafe

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
- Text‑centric images, comics, diagrams, line art: 1.0 – 2.0
- Mixed content: choose based on what is most important to read

5. Dithering (range: 0 – 100)
Purpose: simulate gradients on a 4‑level grayscale display.

Guidelines:
- High gradient content (photos, skies, soft shading): 70 – 100
- Low gradient content (comics, diagrams, UI, line art): 0 – 50
- Lower dithering preserves stronger tonal contrast

────────────────────────
OUTPUT RULES
────────────────────────

- Return ONLY values allowed by the output schema
- Do NOT explain reasoning
- Do NOT include extra text
"""

def analyze_image(image_input, post_title="", post_url="", target_resolution=(400, 300), custom_prompt=None) -> ImageRenderIntent:
    """
    Analyzes an image (URL or PIL Image) using OpenAI Vision and returns a structured style object.
    """
    system_prompt = custom_prompt if custom_prompt else DEFAULT_SYSTEM_PROMPT
    
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
        {"type": "input_text", "text": f"Analyze this image for e-paper optimization.\nPost Title: {post_title}\nPost URL: {post_url}\nTarget Resolution: {target_resolution[0]}x{target_resolution[1]}"},
        {
            "type": "input_image",
            "image_url": image_url_str,
            "detail": "low"
        },
    ]

    response = client.responses.parse(
        model="gpt-4o-mini", # Use 4o-mini as it's reliable for vision
        instructions=system_prompt,
        input=[
            {
                "role": "user",
                "content": user_content,
            }
        ],
        text_format=ImageRenderIntent,
    )
    return response.output_parsed
