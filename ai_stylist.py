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

class ImageStyle(BaseModel):
    decision: Literal["use", "skip"]
    content_type: Literal["photo", "comic_cartoon", "text_heavy", "memes", "UI", "charts", "outline", "line arts", "Others"]
    has_text_overlay: bool
    gradient_complexity: Literal["high", "low"]
    contrast_priority: Literal["detail", "bold"]
    resize_method: Literal["crop", "padding", "stretch"]

DEFAULT_SYSTEM_PROMPT = """You are an e-paper image optimization expert. 
Analyze the provided image and metadata (title, URL) to categorize its visual characteristics.
This help choose the best dithering, sharpening, and resizing parameters for an e-paper display.

Required Output Fields & Guidelines:
1. decision:
   - 'use': Image is high quality, relevant, and suitable for e-paper (good contrast, clear subjects, or meaningful text).
   - 'skip': Image is low quality, blurry, contains too much fine detail that won't dither well, is a tracking pixel, or is irrelevant/spam.
2. content_type:
   - 'photo': Real-world photography.
   - 'comic_cartoon': Illustrations, comics, cartoons.
   - 'text_heavy': Images where text is the primary content (e.g., screenshots of text).
   - 'memes': Images with meme-style text overlays.
   - 'UI': Software user interfaces, app screenshots.
   - 'charts': Infographics, diagrams, charts.
   - 'outline': Simple line drawings, outlines.
   - 'line arts': Detailed line art.
   - 'Others': Anything else.
3. has_text_overlay: true if there is clear readable text added on top of the image.
4. gradient_complexity: 'high' for photos/smooth gradients, 'low' for flat colors/UI.
5. contrast_priority: 'detail' to preserve textures, 'bold' to prioritize sharp edges/readability.
6. resize_method: 'crop' to fill the screen (best for photos), 'padding' to show the whole image with borders (best for art/comics), 'stretch' to fill without cropping.
"""

def analyze_image(image_input, post_title="", post_url="", target_resolution=(400, 300), custom_prompt=None) -> ImageStyle:
    """
    Analyzes an image (URL or PIL Image) using OpenAI Vision and returns a structured style object.
    """
    system_prompt = custom_prompt if custom_prompt else DEFAULT_SYSTEM_PROMPT
    
    if not os.getenv("OPENAI_API_KEY"):
        # Fallback if no API key is provided
        return ImageStyle(
            decision="use",
            content_type="Others",
            has_text_overlay=False,
            gradient_complexity="high",
            contrast_priority="detail",
            resize_method="crop"
        )

    # Handle image input
    if isinstance(image_input, str):
        # It's a URL
        image_data = {
            "url": image_input,
            "detail": "low"
        }
    else:
        # It's a PIL Image, convert to base64
        buffered = BytesIO()
        # Resize if very large to save tokens and speed up, but OpenAI handles it too
        image_input.save(buffered, format="JPEG", quality=85)
        base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
        image_data = {
            "url": f"data:image/jpeg;base64,{base64_image}",
            "detail": "low"
        }

    user_content = [
        {"type": "input_text", "text": f"Analyze this image for e-paper optimization.\nPost Title: {post_title}\nPost URL: {post_url}\nTarget Resolution: {target_resolution[0]}x{target_resolution[1]}"},
        {
            "type": "input_image",
            "image_url": image_data,
        },
    ]

    try:
        response = client.responses.parse(
            model="gpt-5-mini",
            instructions=system_prompt,
            input=[
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
            text_format=ImageStyle,
        )
        return response.output_parsed
    except Exception as e:
        print(f"Error calling AI Stylist: {e}")
        # Fallback to safe defaults
        return ImageStyle(
            decision="use",
            content_type="Others",
            has_text_overlay=False,
            gradient_complexity="high",
            contrast_priority="detail",
            resize_method="crop"
        )
