"""
Nano Banana — Mock Provider for testing and local development.

Enabled by setting DEBUG_MODE=true (or 1/yes) in the environment.
When active, generate_image() returns a synthetic PIL image without
making any AI API calls — safe for CI, unit tests, and offline dev.

Usage:
    from nano_banana.mock_provider import get_provider
    provider = get_provider(real_client)   # returns MockProvider if DEBUG_MODE
    img_bytes = provider.generate_image(prompt, ref_bytes)
"""
import io
import os
from PIL import Image, ImageDraw

DEBUG_MODE: bool = os.environ.get("DEBUG_MODE", "").lower() in ("1", "true", "yes")


class MockProvider:
    """
    Drop-in replacement for GeminiClient that never calls the AI API.
    Returns a 1024×1024 synthetic image with the prompt text and a small
    reference-image thumbnail (when provided).
    """

    def generate_image(self, prompt: str, reference_image_bytes: bytes = None) -> bytes:
        """Mimic GeminiClient.generate_image() — returns JPEG bytes."""
        size = (1024, 1024)
        img  = Image.new("RGB", size, (230, 230, 230))
        draw = ImageDraw.Draw(img)

        # Header banner
        draw.rectangle([0, 0, size[0], 60], fill=(60, 60, 160))
        draw.text((size[0] // 2, 30), "MOCK — NO API CALL", fill=(255, 255, 255), anchor="mm")

        # Outer frame
        draw.rectangle([8, 68, size[0] - 8, size[1] - 8], outline=(180, 180, 200), width=2)

        # Prompt preview
        preview = prompt[:250] + ("…" if len(prompt) > 250 else "")
        y = 85
        for line in _wrap(preview, 64):
            draw.text((18, y), line, fill=(60, 60, 60))
            y += 20
            if y > size[1] - 150:
                draw.text((18, y), "… (truncated)", fill=(140, 140, 140))
                break

        # Reference thumbnail in bottom-right corner
        if reference_image_bytes:
            try:
                ref = Image.open(io.BytesIO(reference_image_bytes)).convert("RGB")
                ref.thumbnail((180, 180), Image.LANCZOS)
                rx = size[0] - ref.width - 16
                ry = size[1] - ref.height - 16
                img.paste(ref, (rx, ry))
                draw.rectangle(
                    [rx - 1, ry - 1, rx + ref.width + 1, ry + ref.height + 1],
                    outline=(100, 100, 200), width=1,
                )
                draw.text((rx + ref.width // 2, ry - 12), "ref", fill=(120, 120, 180), anchor="mm")
            except Exception:
                pass

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()

    def edit_image(self, image_bytes: bytes, instruction: str) -> bytes:
        return self.generate_image(f"[EDIT] {instruction}", reference_image_bytes=image_bytes)


def get_provider(real_client):
    """
    Return MockProvider if DEBUG_MODE is set, otherwise return real_client unchanged.
    Call this at the top of any function that calls generate_image().
    """
    if DEBUG_MODE:
        return MockProvider()
    return real_client


def _wrap(text: str, width: int) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        probe = (current + " " + word).strip()
        if len(probe) <= width:
            current = probe
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
