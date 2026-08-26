# Compilation instructions
# nuitka-project: --standalone

# nuitka-project-if: {OS} == "Windows":
#     nuitka-project: --output-filename=chrome-lens
# nuitka-project-if: {OS} == "Linux":
#     nuitka-project: --output-filename=chrome-lens.bin

# Windows-specific metadata for the executable
# nuitka-project-if: {OS} == "Windows":
#     nuitka-project-set: APP_VERSION = __import__("_version").__version__
#     nuitka-project: --file-description="Chrome Lens OCR CLI"
#     nuitka-project: --file-version={APP_VERSION}
#     nuitka-project: --product-name="Chrome-Lens-OCR-CLI"
#     nuitka-project: --product-version={APP_VERSION}
#     nuitka-project: --copyright="timminator"

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Literal, Union

from chrome_lens_ocr.api import LensAPI
from chrome_lens_ocr.constants import (
    DEFAULT_API_KEY,
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_CONFIG_FILENAME,
)
from chrome_lens_ocr.exceptions import LensConfigError, LensException
from chrome_lens_ocr.utils.config_manager import (
    build_app_config,
    get_default_config_dir,
    update_config_file_from_cli,
)
from chrome_lens_ocr.utils.general import is_image_file_supported


def setup_logging(level_str: str = "WARNING") -> None:
    log_level = getattr(logging, level_str.upper(), logging.WARNING)
    log_format = "[%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s" if log_level <= logging.DEBUG else "%(message)s"
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.debug(f"Logging level set to {level_str.upper()}")


def print_help() -> None:
    print("\nGoogle Lens CLI")
    print("Performs OCR and optional translation on an image.\n")
    print("Usage: chrome-lens <image_source> [ocr_lang] [options]\n")

    print("Arguments:")
    print("  image_source                  Path to an image file, a URL, or a directory.")
    print("  ocr_lang                      BCP 47 language code for OCR (e.g., 'en', 'ja'). If omitted, auto-detection is attempted.\n")

    print("Translation Options:")
    print("  -t, --translate TARGET_LANG   Target language for translation (e.g., 'en', 'ru').")
    print("  --translate-from SOURCE_LANG  Source language for translation (auto-detected if omitted).")

    print("Output and Config Options:")
    print("  -b, --output-blocks           Output OCR text as segmented blocks (useful for comics).")
    print("  -ol, --output-lines           Output OCR text as individual lines with their geometry.")
    print("  --get-coords                  Output recognized words with their coordinates in JSON format.")
    print(
        "  --oneline                     Print JSON output on a single line (only applies when used with --get-coords, useful for piping/streaming)."
    )
    print("  -q, --quiet                   Suppress informational messages and headers, printing only the final result data.")
    print("  --ocr-single-line             Join all OCR text into a single line (preserves line breaks by default).")
    print("  --config-file FILE_PATH       Path to a custom JSON configuration file.")
    print("  --update-config               Update the default config file with CLI arguments.")

    print("Advanced & Debug Options:")
    print("  --api-key KEY                 Google Cloud API key (overrides config).")
    print("  --proxy URL                   Proxy server URL (e.g., http://user:pass@host:port, socks5://host:port).")
    print("  --timeout SECONDS             Request timeout in seconds (default: 60).")
    print("  --concurrency N               Set the maximum number of concurrent requests (default: 3).")
    print("  --retries                     Maximum number of retries for failed network requests (default: 3). Set to 0 to disable.")
    print(f"  --client-region REGION        Client region code (default: '{DEFAULT_CLIENT_REGION}').")
    print(f"  --client-time-zone TZ         Client time zone ID (default: '{DEFAULT_CLIENT_TIME_ZONE}').")
    print("  -l, --logging-level LEVEL     Set logging level (DEBUG, INFO, WARNING, ERROR).")
    print("  -h, --help                    Show this help message and exit.")


async def cli_main() -> None:
    parser = argparse.ArgumentParser(description="Google Lens CLI", add_help=False)
    # Positional
    parser.add_argument("image_source", nargs="?", help="Path to the image file, a URL, or a directory.")
    parser.add_argument("ocr_lang", nargs="?", default=None, help="BCP 47 code for OCR.")
    # Translation
    parser.add_argument("-t", "--translate", dest="target_lang")
    parser.add_argument("--translate-from", dest="source_lang")
    # Output & Config
    parser.add_argument(
        "-b",
        "--output-blocks",
        action="store_true",
        help="Output OCR text as segmented blocks.",
    )
    parser.add_argument(
        "-ol",
        "--output-lines",
        action="store_true",
        help="Output OCR text as individual lines.",
    )
    parser.add_argument(
        "--get-coords",
        action="store_true",
        help="Output word coordinates in JSON format.",
    )
    parser.add_argument(
        "--oneline",
        action="store_true",
        help="Print JSON output on a single line (only applies when used with --get-coords, useful for piping/streaming).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress informational messages, printing only result data.",
    )
    parser.add_argument(
        "--ocr-single-line",
        action="store_false",
        dest="ocr_preserve_line_breaks",
        default=None,
    )
    parser.add_argument("--config-file", dest="config_file_path_override")
    parser.add_argument("--update-config", action="store_true")
    # Advanced
    parser.add_argument("--api-key")
    parser.add_argument("--proxy")
    parser.add_argument("--timeout", type=int)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Maximum number of concurrent requests (default: 3).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum number of retries for failed network requests (default: 3). Set to 0 to disable.",
    )
    parser.add_argument("--client-region")
    parser.add_argument("--client-time-zone")
    # Meta
    parser.add_argument("-l", "--logging-level", dest="logging_level")
    parser.add_argument("-h", "--help", action="store_true")

    args = parser.parse_args()

    MAX_CONCURRENCY_HARD_LIMIT = 30
    CONCURRENCY_WARNING_THRESHOLD = 20

    if args.concurrency > MAX_CONCURRENCY_HARD_LIMIT:
        print(f"Error: The concurrency value cannot be greater than {MAX_CONCURRENCY_HARD_LIMIT}.")
        print("This is a security measure to prevent IP blocking.")
        sys.exit(1)

    if args.concurrency > CONCURRENCY_WARNING_THRESHOLD:
        print(f"Warning: High concurrency value ({args.concurrency}) set.")
        print("This may result in a temporary block by Google. Use with caution.")

    if args.help:
        print_help()
        return
    if not args.image_source:
        print("Error: The 'image_source' argument is required.\n")
        print_help()
        sys.exit(1)

    # Validate mutually exclusive output formats
    output_modes = [args.output_blocks, args.get_coords, args.output_lines]
    if sum(output_modes) > 1:
        print("Error: --output-blocks, --output-lines, and --get-coords cannot be used together.")
        sys.exit(1)

    default_config_path = os.path.join(get_default_config_dir(), DEFAULT_CONFIG_FILENAME)
    config_file_to_load = args.config_file_path_override or default_config_path

    try:
        app_config = build_app_config(vars(args), config_file_to_load)
    except LensConfigError as e:
        print(f"Configuration Error: {e}")
        sys.exit(1)

    setup_logging(app_config.get("logging_level", "WARNING"))

    if os.path.exists(config_file_to_load):
        logging.info(f"Using config file: {config_file_to_load}")
    elif args.config_file_path_override:
        logging.warning(f"Specified config file not found: {args.config_file_path_override}")

    image_sources = []
    if os.path.isdir(args.image_source):
        if not args.quiet:
            print(f"Processing directory: {args.image_source}")
        for filename in sorted(os.listdir(args.image_source)):
            full_path = os.path.join(args.image_source, filename)
            if is_image_file_supported(full_path):
                image_sources.append(full_path)
        if not image_sources:
            print(f"Error: No supported image files found in directory '{args.image_source}'.")
            sys.exit(1)
    else:
        if not is_image_file_supported(args.image_source):
            print(f"Error: Source '{args.image_source}' is not a valid URL or supported image file.")
            sys.exit(1)
        image_sources.append(args.image_source)

    if args.update_config:
        if args.config_file_path_override:
            print("Warning: --update-config only affects the default config file.")
        else:
            try:
                update_config_file_from_cli(vars(args), default_config_path)
            except LensConfigError as e:
                print(f"Error updating config: {e}")

    api = LensAPI(
        api_key=app_config.get("api_key", DEFAULT_API_KEY),
        client_region=app_config.get("client_region"),
        client_time_zone=app_config.get("client_time_zone"),
        proxy=app_config.get("proxy"),
        timeout=app_config.get("timeout", 60),
        max_concurrent=args.concurrency,
        max_retries=args.retries,
    )

    try:
        output_format: Literal["full_text", "blocks", "lines", "detailed"] = "full_text"
        if args.output_blocks:
            output_format = "blocks"
        elif args.output_lines:
            output_format = "lines"

        results_buffer: dict[int, Union[dict[str, Any], Exception]] = {}
        next_to_print = 0
        results_ready = asyncio.Condition()

        async def worker(queue: "asyncio.Queue[tuple[int, str]]") -> None:
            while True:
                index, path = await queue.get()
                try:
                    result: Union[dict[str, Any], Exception]
                    try:
                        result = await api.process_image(
                            image_path=path,
                            ocr_language=args.ocr_lang,
                            target_translation_language=args.target_lang,
                            source_translation_language=args.source_lang,
                            ocr_preserve_line_breaks=app_config.get("ocr_preserve_line_breaks", True),
                            output_format=output_format,
                        )
                    except Exception as e:
                        result = e

                    async with results_ready:
                        results_buffer[index] = result
                        results_ready.notify()

                finally:
                    queue.task_done()

        job_queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        for i, path in enumerate(image_sources):
            job_queue.put_nowait((i, path))

        # Pre-processing buffer.
        PRE_PROCESS_MULTIPLIER = 2
        num_workers = min(len(image_sources), args.concurrency * PRE_PROCESS_MULTIPLIER)

        worker_tasks = [asyncio.create_task(worker(job_queue)) for _ in range(num_workers)]

        while next_to_print < len(image_sources):

            def is_ready(target: int = next_to_print) -> bool:
                return target in results_buffer

            async with results_ready:
                await results_ready.wait_for(is_ready)

            result = results_buffer.pop(next_to_print)
            image_path = image_sources[next_to_print]

            if isinstance(result, Exception):
                print(f"\n- ({next_to_print + 1}/{len(image_sources)}) Error for: {os.path.basename(image_path)} -")
                print(f"{result}")
                next_to_print += 1
                continue

            if len(image_sources) > 1 and not args.quiet:
                print(f"\n- ({next_to_print + 1}/{len(image_sources)}) Result for: {os.path.basename(image_path)} -")

            if args.get_coords:
                word_data = result.get("word_data")
                image_dimensions = result.get("image_dimensions")

                indent_val = None if args.oneline else 2

                if not word_data:
                    empty_data = {"file": os.path.basename(image_path), "dimensions": image_dimensions, "words": []}
                    print(json.dumps(empty_data, indent=indent_val, ensure_ascii=False))
                    next_to_print += 1
                    continue

                processed_coords = []
                for data in word_data:
                    geom = data.get("geometry")
                    processed_coords.append({
                        "text": data["word"],
                        "separator": data["separator"] or "",
                        "geometry": (
                            {
                                "center_x": round(geom["center_x"], 4),
                                "center_y": round(geom["center_y"], 4),
                                "width": round(geom["width"], 4),
                                "height": round(geom["height"], 4),
                                "angle_deg": round(geom["angle_deg"], 2),
                            }
                            if geom
                            else None
                        ),
                    })

                output_data = {"file": os.path.basename(image_path), "dimensions": image_dimensions, "words": processed_coords}
                print(json.dumps(output_data, indent=indent_val, ensure_ascii=False))

            elif args.output_lines:
                line_blocks = result.get("line_blocks", [])
                if not args.quiet:
                    print(f"\nOCR Results ({len(line_blocks)} lines):")
                if not line_blocks and not args.quiet:
                    print("No lines found.")

                for j, line in enumerate(line_blocks):
                    if not args.quiet:
                        print(f"\n--- Line #{j + 1} ---")
                    print(line.get("text", ""))

                translated_text = result.get("translated_text")
                if translated_text:
                    if not args.quiet:
                        print("\nTranslated Text (Full):")
                    print(translated_text)

            elif args.output_blocks:
                text_blocks = result.get("text_blocks", [])
                if not args.quiet:
                    print(f"\nOCR Results ({len(text_blocks)} blocks):")
                if not text_blocks and not args.quiet:
                    print("No text blocks found.")

                for j, block in enumerate(text_blocks):
                    if not args.quiet:
                        print(f"\n--- Block #{j + 1} ---")
                    print(block.get("text", ""))

                translated_text = result.get("translated_text")
                if translated_text:
                    if not args.quiet:
                        print("\nTranslated Text (Full):")
                    print(translated_text)

            else:  # Default 'full_text' output
                ocr_text = result.get("ocr_text")
                if ocr_text:
                    if not args.quiet:
                        print("\nOCR Results:")
                    print(ocr_text)
                elif not args.quiet:
                    print("\nOCR Results:")
                    print("No OCR text found.")

                translated_text = result.get("translated_text")
                if translated_text:
                    if not args.quiet:
                        print("\nTranslated Text:")
                    print(translated_text)

            translated_text = result.get("translated_text")
            if args.target_lang and not translated_text and not args.quiet:
                print("\nTranslation was requested but not found in the response.")

            next_to_print += 1

        await job_queue.join()
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        await api.request_handler.close()

    except LensException as e:
        print(f"\nLens API Error: {e}")
        sys.exit(1)


def run() -> None:
    if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
        try:
            os.system("chcp 65001 > nul")
            logging.debug("Set Windows console to chcp 65001 (UTF-8)")
        except Exception as e:
            print(f"Warning: Failed to set console to UTF-8 (chcp 65001). Error: {e}")
    try:
        asyncio.run(cli_main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")


if __name__ == "__main__":
    run()
