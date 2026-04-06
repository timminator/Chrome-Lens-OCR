import asyncio
import functools
import logging
from math import pi
from typing import TYPE_CHECKING, Any, Literal, Optional, Union

import httpx

from .constants import (
    DEFAULT_API_KEY,
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_OCR_LANG,
)
from .core.image_processor import (
    get_word_geometry_data,
    prepare_image_for_api,
)
from .core.protobuf_builder import create_ocr_translate_request
from .core.request_handler import LensRequestHandler
from .exceptions import LensException

if TYPE_CHECKING:
    from .utils.lens_betterproto import (
        LensOverlayServerResponse,
        TextLayoutLine,
        TextLayoutParagraph,
        TextLayoutWord,
        TranslationDataStatusCode,
    )
else:
    from .utils.lens_betterproto import (
        LensOverlayServerResponse,
        TextLayoutLine,
        TextLayoutParagraph,
        TextLayoutWord,
        TranslationDataStatusCode,
    )

logger = logging.getLogger(__name__)


class LensAPI:
    """
    Main class for interacting with the Google Lens API.
    Provides methods for OCR, translation, and text block segmentation.
    """

    def __init__(
        self,
        api_key: str = DEFAULT_API_KEY,
        client_region: Optional[str] = None,
        client_time_zone: Optional[str] = None,
        proxy: Optional[Union[str, dict[str, httpx.AsyncBaseTransport]]] = None,
        timeout: int = 60,
        max_concurrent: int = 10,
        max_retries: int = 3,
    ):
        """
        Initializes the LensAPI client.

        :param api_key: Your Google API key. Defaults to the library's built-in key.
        :param client_region: ISO 3166-1 alpha-2 country code (e.g., 'US', 'DE').
        :param client_time_zone: Time zone name (e.g., 'America/New_York').
        :param proxy: Proxy server URL or a dictionary for mounting transports.
        :param timeout: Request timeout in seconds.
        :param max_concurrent: The maximum number of concurrent requests to prevent API abuse. Defaults to 5.
        """
        self.request_handler = LensRequestHandler(api_key=api_key, proxy=proxy, timeout=timeout, max_retries=max_retries)
        self.client_region = client_region
        self.client_time_zone = client_time_zone
        self._semaphore = asyncio.Semaphore(max_concurrent)
        if max_concurrent > 20:
            logger.warning(f"max_concurrent is set to {max_concurrent}, which is very high. This may lead to IP bans. Use with caution.")

    def _parse_line(self, line: "TextLayoutLine") -> dict[str, Any]:
        """Parses a single TextLayoutLine into a structured dictionary."""
        line_text = "".join(word.plain_text + (word.text_separator or "") for word in line.words).strip()

        l_geom = line.geometry.bounding_box
        geometry_dict = {
            "center_x": l_geom.center_x,
            "center_y": l_geom.center_y,
            "width": l_geom.width,
            "height": l_geom.height,
            "angle_deg": l_geom.rotation_z * (180 / pi) if l_geom.rotation_z else 0.0,
        }

        return {
            "text": line_text,
            "geometry": geometry_dict,
        }

    def _parse_paragraph(self, paragraph: "TextLayoutParagraph") -> dict[str, Any]:
        """Parses a single TextLayoutParagraph into a structured dictionary."""
        paragraph_lines = []
        for line in paragraph.lines:
            # Fixed Pylance issue: use 'or ""' to handle optional separator
            current_line_text = "".join(word.plain_text + (word.text_separator or "") for word in line.words)
            paragraph_lines.append(current_line_text.strip())

        full_paragraph_text = "\n".join(paragraph_lines)

        p_geom = paragraph.geometry.bounding_box
        geometry_dict = {
            "center_x": p_geom.center_x,
            "center_y": p_geom.center_y,
            "width": p_geom.width,
            "height": p_geom.height,
            "angle_deg": p_geom.rotation_z * (180 / pi) if p_geom.rotation_z else 0.0,
        }

        return {
            "text": full_paragraph_text,
            "lines": paragraph_lines,
            "geometry": geometry_dict,
        }

    def _extract_ocr_data_from_response(
        self,
        response_proto: "LensOverlayServerResponse",
        preserve_line_breaks: bool = True,
        output_format: Literal["full_text", "blocks", "lines", "detailed"] = "full_text",
    ) -> tuple[Union[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """
        Extracts OCR data from the response.
        """
        word_data_list: list[dict[str, Any]] = []
        if not (
            response_proto.objects_response and response_proto.objects_response.text and response_proto.objects_response.text.text_layout
        ):
            if output_format == "full_text":
                return "", []
            return [], []

        text_layout = response_proto.objects_response.text.text_layout

        for paragraph in text_layout.paragraphs:
            for line in paragraph.lines:
                for word in line.words:
                    word_data_list.append({
                        "word": word.plain_text,
                        "separator": word.text_separator,
                        "geometry": (
                            get_word_geometry_data(word.geometry.bounding_box) if word.geometry and word.geometry.bounding_box else None
                        ),
                    })

        detected_lang = getattr(response_proto.objects_response.text, "content_language", "N/A")
        logger.info(f"Extracted data for {len(word_data_list)} words. Detected language: {detected_lang}")

        if output_format == "detailed":
            detailed_blocks = [self._parse_paragraph_detailed(p) for p in text_layout.paragraphs]
            return detailed_blocks, word_data_list

        if output_format == "lines":
            line_blocks = []
            for p in text_layout.paragraphs:
                for line in p.lines:
                    line_blocks.append(self._parse_line(line))
            return line_blocks, word_data_list

        if output_format == "blocks":
            text_blocks = [self._parse_paragraph(p) for p in text_layout.paragraphs]
            return text_blocks, word_data_list
        else:  # 'full_text'
            if preserve_line_breaks:
                full_ocr_text = "\n".join("\n".join(self._parse_paragraph(p)["lines"]) for p in text_layout.paragraphs)
            else:
                text_parts = [data["word"] + (data["separator"] or "") for data in word_data_list]
                full_ocr_text = "".join(text_parts).strip()
                full_ocr_text = " ".join(full_ocr_text.split())

            return full_ocr_text, word_data_list

    def _extract_translation_from_response(self, response_proto: "LensOverlayServerResponse") -> Optional[str]:
        """Extracts and consolidates all successful translations."""
        all_translations = []
        if response_proto.objects_response and response_proto.objects_response.deep_gleams:
            for gleam in response_proto.objects_response.deep_gleams:
                if gleam.translation and gleam.translation.status.code == TranslationDataStatusCode.SUCCESS:
                    if gleam.translation.translation:
                        all_translations.append(gleam.translation.translation)
        return "\n".join(all_translations).strip() or None

    def _parse_word_detailed(self, word: "TextLayoutWord") -> dict[str, Any]:
        """Parses a single TextLayoutWord into a detailed dictionary including geometry."""
        geometry_data = get_word_geometry_data(word.geometry.bounding_box) if word.geometry and word.geometry.bounding_box else None
        return {
            "text": word.plain_text,
            "separator": word.text_separator,
            "geometry": geometry_data,
        }

    def _parse_line_detailed(self, line: "TextLayoutLine") -> dict[str, Any]:
        """Parses a TextLayoutLine into a detailed dictionary with words and geometry."""
        line_text = "".join(word.plain_text + (word.text_separator or "") for word in line.words).strip()

        l_geom = line.geometry.bounding_box
        geometry_dict = {
            "center_x": l_geom.center_x,
            "center_y": l_geom.center_y,
            "width": l_geom.width,
            "height": l_geom.height,
            "angle_deg": l_geom.rotation_z * (180 / pi) if l_geom.rotation_z else 0.0,
        }

        return {
            "text": line_text,
            "geometry": geometry_dict,
            "words": [self._parse_word_detailed(word) for word in line.words],
        }

    def _parse_paragraph_detailed(self, paragraph: "TextLayoutParagraph") -> dict[str, Any]:
        """Parses a TextLayoutParagraph into a detailed dictionary with lines and geometry."""
        full_paragraph_text = "\n".join(
            "".join(word.plain_text + (word.text_separator or "") for word in line.words).strip() for line in paragraph.lines
        )

        p_geom = paragraph.geometry.bounding_box
        geometry_dict = {
            "center_x": p_geom.center_x,
            "center_y": p_geom.center_y,
            "width": p_geom.width,
            "height": p_geom.height,
            "angle_deg": p_geom.rotation_z * (180 / pi) if p_geom.rotation_z else 0.0,
        }

        return {
            "text": full_paragraph_text,
            "geometry": geometry_dict,
            "lines": [self._parse_line_detailed(line) for line in paragraph.lines],
        }

    async def process_image(
        self,
        image_path: str,
        ocr_language: Optional[str] = None,
        target_translation_language: Optional[str] = None,
        source_translation_language: Optional[str] = None,
        new_session: bool = True,
        ocr_preserve_line_breaks: bool = True,
        output_format: Literal["full_text", "blocks", "lines", "detailed"] = "full_text",
    ) -> dict[str, Any]:
        """
        Processes an image, performing OCR and optional translation.

        :param image_path: Path to a file (str or pathlib.Path) or URL.
        :param ocr_language: BCP 47 language code for OCR (e.g., 'en', 'ja').
        :param target_translation_language: BCP 47 language code for translation target.
        :param source_translation_language: BCP 47 language code for translation source.
        :param new_session: If True, starts a new server session for the request.
        :param ocr_preserve_line_breaks: If True and output_format is 'full_text', preserves line breaks.
        :param output_format: 'full_text' (default) returns a single string in 'ocr_text'.
                            'blocks' returns a list of dictionaries in 'text_blocks'.
                            'lines' returns a list of dictionaries in 'line_blocks',
                            each representing a single recognized line with its geometry.
        :return: A dictionary containing the processing results.
        """
        logger.info(f"Processing image source: {image_path[:120]}...")

        try:
            img_bytes, width, height, original_width, original_height = await prepare_image_for_api(image_path)

            if new_session:
                self.request_handler.start_new_session()

            session_uuid_for_request, seq_id, img_seq_id = self.request_handler.get_next_sequence_ids_for_request(
                is_new_image_payload=new_session
            )

            # Package the function and args to offload Protobuf Serialization
            build_proto_func = functools.partial(
                create_ocr_translate_request,
                image_bytes=img_bytes,
                width=width,
                height=height,
                ocr_language=ocr_language or DEFAULT_OCR_LANG,
                target_translation_language=target_translation_language,
                source_translation_language=source_translation_language,
                client_region=self.client_region or DEFAULT_CLIENT_REGION,
                client_time_zone=self.client_time_zone or DEFAULT_CLIENT_TIME_ZONE,
                session_uuid=session_uuid_for_request,
                sequence_id=seq_id,
                image_sequence_id=img_seq_id,
                routing_info=(self.request_handler.last_cluster_info.routing_info if self.request_handler.last_cluster_info else None),
            )

            # OFFLOAD TO THREAD
            proto_payload, uuid_for_this_request = await asyncio.to_thread(build_proto_func)

            async with self._semaphore:
                response_proto = await self.request_handler.send_request(proto_payload, request_uuid_used=uuid_for_this_request)

            ocr_result, word_data = self._extract_ocr_data_from_response(response_proto, ocr_preserve_line_breaks, output_format)

            translated_text = self._extract_translation_from_response(response_proto) if target_translation_language else None

            final_result = {
                "translated_text": translated_text,
                "word_data": word_data,
                "raw_response_objects": response_proto.objects_response,
                "image_dimensions": {
                    "original_width": original_width,
                    "original_height": original_height,
                    "scaled_width": width,
                    "scaled_height": height,
                },
            }

            if output_format == "detailed":
                final_result["detailed_blocks"] = ocr_result
            elif output_format == "blocks":
                final_result["text_blocks"] = ocr_result
            elif output_format == "lines":
                final_result["line_blocks"] = ocr_result
            else:
                final_result["ocr_text"] = ocr_result

            return final_result

        except LensException as e:
            logger.error(f"LensAPI processing error: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error in LensAPI: {e}", exc_info=True)
            raise LensException(f"Unexpected error in LensAPI: {e}") from e
