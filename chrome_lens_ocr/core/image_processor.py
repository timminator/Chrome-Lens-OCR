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
    from ..utils.lens_betterproto import CenterRotatedBox
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
        except httpx.RequestError as e:
            raise LensImageError(f"Network error downloading URL '{image_source}': {e}") from e
        except Exception as e:
            raise LensImageError(f"Error processing URL '{image_source}': {e}") from e
    else:
        logger.debug(f"Reading raw bytes from file path: {image_source}")
        try:

            def read_file() -> bytes:
                with open(image_source, "rb") as f:
                    return f.read()

            return await asyncio.to_thread(read_file)
        except FileNotFoundError:
            raise LensImageError(f"File not found at path: {image_source}") from None
        except Exception as e:
            raise LensImageError(f"Error reading file path '{image_source}': {e}") from e


def _resize_and_serialize_pil_image(pil_image: Image.Image) -> tuple[bytes, int, int]:
    """Resizes (if necessary) and serializes a PIL.Image to JPEG bytes."""
    if pil_image.mode in ("RGBA", "P"):
        pil_image = pil_image.convert("RGB")

    if pil_image.width > DEFAULT_IMAGE_MAX_DIMENSION or pil_image.height > DEFAULT_IMAGE_MAX_DIMENSION:
        pil_image.thumbnail(
            (DEFAULT_IMAGE_MAX_DIMENSION, DEFAULT_IMAGE_MAX_DIMENSION),
            Image.Resampling.LANCZOS,
        )

    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format="JPEG", quality=95)

    return img_byte_arr.getvalue(), pil_image.width, pil_image.height


async def prepare_image_for_api(image_source: str) -> tuple[bytes, int, int, int, int]:
    """
    Main preparation function. Takes any source, processes it, and returns API-ready data
    along with the scaled and original dimensions.
    """
    try:
        raw_bytes = await _get_raw_bytes_from_source(image_source)
        pil_image = await asyncio.to_thread(Image.open, io.BytesIO(raw_bytes))

        original_width = pil_image.width
        original_height = pil_image.height

        if pil_image.format == "JPEG" and original_width <= DEFAULT_IMAGE_MAX_DIMENSION and original_height <= DEFAULT_IMAGE_MAX_DIMENSION:
            logger.debug(f"Bypassing image re-encoding. Native format: {pil_image.format}")
            return raw_bytes, original_width, original_height, original_width, original_height

        logger.debug(f"Re-encoding required. Native format: {pil_image.format}, Size: {original_width}x{original_height}")
        img_bytes, scaled_width, scaled_height = await asyncio.to_thread(_resize_and_serialize_pil_image, pil_image)

        return img_bytes, scaled_width, scaled_height, original_width, original_height

    except LensImageError as e:
        raise e
    except Exception as e:
        raise LensImageError(f"An unexpected error occurred during image preparation: {e}") from e


def get_word_geometry_data(box: "CenterRotatedBox") -> Optional[dict[str, Any]]:
    """Extracts detailed, user-friendly geometry data from a CenterRotatedBox object."""
    if not (hasattr(box, "center_x") and hasattr(box, "center_y")):
        return None

    angle_rad = getattr(box, "rotation_z", 0.0)
    angle_deg = math.degrees(angle_rad)

    coord_type_enum = getattr(box, "coordinate_type", 0)
    coord_type_str = "NORMALIZED" if coord_type_enum == 1 else "IMAGE"

    return {
        "center_x": box.center_x,
        "center_y": box.center_y,
        "width": getattr(box, "width", 0.0),
        "height": getattr(box, "height", 0.0),
        "angle_deg": angle_deg,
        "coordinate_type": coord_type_str,
    }
