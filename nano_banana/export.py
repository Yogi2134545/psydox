"""Nano Banana — export utilities."""
import io
import zipfile
from PIL import Image


class Exporter:
    def to_bytes(self, image: Image.Image, fmt: str = "JPEG", quality: int = 90) -> bytes:
        """Convert PIL image to bytes in the specified format."""
        buf = io.BytesIO()
        fmt_upper = fmt.upper()
        save_img = image

        if fmt_upper == "JPEG":
            save_img = image.convert("RGB")
            save_img.save(buf, format="JPEG", quality=quality, optimize=True)
        elif fmt_upper == "PNG":
            save_img.save(buf, format="PNG", optimize=True)
        elif fmt_upper == "WEBP":
            save_img.save(buf, format="WEBP", quality=quality)
        else:
            save_img = image.convert("RGB")
            save_img.save(buf, format="JPEG", quality=quality)

        return buf.getvalue()

    def batch_to_zip(
        self, images: list, fmt: str = "JPEG", quality: int = 90
    ) -> bytes:
        """
        Create a ZIP of multiple images.

        images: list of (name, PIL.Image) tuples or PIL.Image list.
        """
        buf = io.BytesIO()
        ext = fmt.lower()
        if ext == "jpeg":
            ext = "jpg"

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, item in enumerate(images):
                if isinstance(item, tuple):
                    name, img = item
                else:
                    name = f"image_{i+1:03d}.{ext}"
                    img = item
                if not name.endswith(f".{ext}"):
                    name = f"{name}.{ext}"
                # Accept pre-encoded bytes directly to avoid redundant PIL round-trip
                if isinstance(img, (bytes, bytearray)):
                    zf.writestr(name, img)
                else:
                    img_bytes = self.to_bytes(img, fmt, quality)
                    zf.writestr(name, img_bytes)

        return buf.getvalue()
