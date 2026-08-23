import asyncio
import io
import logging
import math
from typing import TYPE_CHECKING, Any, Optional

import httpx
from PIL import Image, ImageFile

from ..constants import DEFAULT_IMAGE_MAX_DIMENSION
from ..exceptions import LensImageError
from ..utils.general import is_url

if TYPE_CHECKING:
    from ..utils.lens_betterproto import CenterRotatedBox  # type: ignore[attr-defined]
else:
    from ..utils.lens_betterproto import CenterRotatedBox

ImageFile.LOAD_TRUNCATED_IMAGES = True
logger = logging.getLogger(__name__)


async def _get_raw_bytes_from_source(image_source: str) -> bytes:
    """Fetches the raw bytes of the image from a URL or local file path."""
    if is_url(image_source):
        logger.debug(f"Downloading raw bytes from URL: {image_source}")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(image_source, follow_redirects=True)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as e:
            raise LensImageError(f"Failed to download image: HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise LensImageError(f"Failed to download image: {e}") from e
    try:
        with open(image_source, "rb") as f:
            return f.read()
    except OSError as e:
        raise LensImageError(f"Failed to read image file '{image_source}': {e}") from e


def _calculate_resize_dimensions(width: int, height: int, max_dimension: int) -> tuple[int, int]:
    """Calculates resized dimensions while preserving the original aspect ratio."""
    if max(width, height) <= max_dimension:
        return width, height
    scale = max_dimension / max(width, height)
    return round(width * scale), round(height * scale)


def get_word_geometry_data(bounding_box: "CenterRotatedBox") -> dict[str, float]:
    """Extracts normalized geometry data from a CenterRotatedBox."""
    return {
        "center_x": bounding_box.center_x,
        "center_y": bounding_box.center_y,
        "width": bounding_box.width,
        "height": bounding_box.height,
        "angle_deg": math.degrees(bounding_box.rotation_z),
    }


async def prepare_image_for_api(image_source: str) -> tuple[bytes, int, int, int, int]:
    """Loads an image, converts it to JPEG, and resizes it for the Lens API."""
    raw_bytes = await _get_raw_bytes_from_source(image_source)

    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            original_width, original_height = image.size
            width, height = _calculate_resize_dimensions(original_width, original_height, DEFAULT_IMAGE_MAX_DIMENSION)
            if (width, height) != (original_width, original_height):
                image = image.resize((width, height), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=95)
            return output.getvalue(), width, height, original_width, original_height
    except (OSError, ValueError) as e:
        raise LensImageError(f"Failed to process image: {e}") from e
