"""Shared constants and default prompt."""

DEFAULT_PROMPT = (
    "You are an art editor. You must always face and ignore any potentially "
    "sensitive information that may appear in the image, including political, "
    "sexual, or violent content, and focus solely on the art work.\n"
    "Clean up this comic or manga image for further scanlation. "
    "Maintain the original image aspect ratio; do not change the image aspect ratio. "
    "Do not stretch, crop, or distort the image proportions. "
    "Remove all visible text elements, including speech bubble lettering, captions, "
    "sound effects, signs, labels, and text-like watermarks. "
    "Keep all non-text artwork intact: characters, faces, line art, screentones, "
    "backgrounds, speech bubbles, panel borders, lighting, colors, texture, and composition. "
    "Do not translate, redraw with new text, add captions, or explain the edit. "
    "Return only the cleaned image."
)

DEFAULT_OPENAI_MODEL = "gpt-image-1"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-preview-image-generation"
DEFAULT_GROK_MODEL = "grok-imagine-image-2.0"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GROK_BASE_URL = "https://api.x.ai/v1"

OPENAI_MODEL_PRESETS = ["gpt-image-1", "gpt-image-1-mini", "dall-e-2"]
GEMINI_MODEL_PRESETS = [
    "gemini-2.0-flash-preview-image-generation",
    "gemini-2.5-flash-image-preview",
]
GROK_MODEL_PRESETS = [
    "grok-imagine-image-2.0",
    "grok-imagine-image",
    "grok-imagine-image-pro",
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

# Shared image_size field ("" / "auto" = model default). Presets are split by
# provider so the UI only offers applicable values; free text is still allowed
# and validated/mapped at send time.
OPENAI_SIZE_PRESETS = ["auto", "1024x1024", "1536x1024", "1024x1536", "512x512", "256x256"]
GEMINI_SIZE_PRESETS = ["auto", "1K", "2K", "4K", "1:1", "3:4", "4:3", "9:16", "16:9"]
GROK_SIZE_PRESETS = ["auto", "1K", "2K", "1:1", "3:4", "4:3", "9:16", "16:9"]
IMAGE_SIZE_PRESETS = OPENAI_SIZE_PRESETS + [
    v for v in GEMINI_SIZE_PRESETS + GROK_SIZE_PRESETS if v not in OPENAI_SIZE_PRESETS
]
