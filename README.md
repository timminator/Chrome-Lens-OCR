<p align="center">
  <h1 align="center">Chrome-Lens-OCR</h1>
  <p align="center">
    Use Google Lens OCR for free from the command line - via the API used in Chromium!<br>
    <br />
  </p>
</p>

<br>

This project provides a powerful, asynchronous Python library wrapped in a command-line interface for interacting with Google Lens. It allows you to perform advanced Optical Character Recognition (OCR), get segmented text blocks (e.g., for comics), translate text, and get precise word coordinates.

## ✨ Key Features

-   **Modern Backend**: Utilizes Google's official Protobuf endpoint (`v1/crupload`) for robust and accurate results.
-   **Asynchronous & Safe**: Built with `asyncio` and `httpx`. Includes a built-in semaphore to prevent API abuse and IP bans from excessive concurrent requests.
-   **Powerful OCR & Segmentation**:
    -   Extract text from images as a single string.
    -   Get text segmented into logical blocks (paragraphs, dialog bubbles) with their own coordinates.
    -   Get individual text lines with their own precise geometry.
-   **Built-in Translation**: Instantly translate recognized text into any supported language.
-   **Proxy Support**: Full support for HTTP, HTTPS, and SOCKS proxies.
-   **Flexible Configuration**: Manage settings via a `config.json` file, CLI arguments, or environment variables.

## 🚀 Usage

<details>
  <summary><b>🛠️ CLI Usage</b></summary>

  The command-line tool provides quick access to the library's features directly from your terminal.

  ```bash
  chrome-lens <image_source> [ocr_lang] [options]
  ```

  -   **`<image_source>`**: Path to a local image file or an image URL.
  -   **`[ocr_lang]`** (optional): BCP 47 language code for OCR (e.g., 'en', 'ja'). If omitted, the API will attempt to auto-detect the language.

  #### **Options**

| Flag | Alias | Description |
| :--- | :--- | :--- |
| `--translate <lang>` | `-t` | **Translate** the OCR text to the target language code (e.g., `en`, `ru`). |
| `--translate-from <lang>` | | Specify the source language for translation (otherwise auto-detected). |
| `--output-blocks` | `-b` | **Output OCR text as segmented blocks** (useful for comics). Incompatible with `--get-coords` and `--output-lines`.|
| `--output-lines` | `-ol` | **Output OCR text as individual lines** with their geometry. Incompatible with `--output-blocks` and `--get-coords`.|
| `--get-coords` | | Output recognized words and their coordinates in JSON format. Incompatible with `--output-blocks` and `--output-lines`. |
| `--oneline` | | Print JSON output on a single line (only applies when used with --get-coords, useful for piping/streaming). |
| `--ocr-single-line` | | Join all recognized OCR text into a single line, removing line breaks. |
| `--config-file <path>`| | Path to a custom JSON configuration file. |
| `--update-config` | | Update the default config file with settings from the current command. |
| `--concurrency N` | | Set the maximum number of concurrent requests (default: 3). |
| `--retries` | | Maximum number of retries for failed network requests (default: 3). Set to 0 to disable. |
| `--proxy <url>` | | Proxy server URL (e.g., `socks5://127.0.0.1:9050`). |
| `--logging-level <lvl>`| `-l` | Set logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `--help` | `-h` | Show this help message and exit. |

  #### **Examples**

  **1. Basic OCR and Translation**
  
  Auto-detects the source language on the image and translates it to English. This is the most common use case.
  ```bash
  chrome-lens "path/to/your/image.png" -t en
  ```

  ---
  
  **2. Get Segmented Text Blocks (for Comics/Manga)**

  Ideal for images with multiple, separate text boxes. This command outputs each recognized text block individually, making it perfect for translating comics or complex documents.
  ```bash
  chrome-lens "path/to/manga.jpg" ja -b
  ```
  - `-b` is the alias for `--output-blocks`.

  ---
  
  **3. Get Individual Text Lines**
  
  Outputs each recognized line of text along with its geometry.
  ```bash
  chrome-lens "path/to/document.png" --output-lines
  ```
  - `-ol` is the alias for `--output-lines`.

  ---

  **4. Get Coordinates of All Individual Words**
  
  Outputs a detailed JSON array containing every single recognized word and its precise geometric data (center, size, angle). Useful for programmatic analysis or custom overlays.
  ```bash
  chrome-lens "path/to/diagram.png" --get-coords
  ```
  
  ---

  ---

  **5. Process an Image from a URL as a Single Line**

  Fetches an image directly from a URL and joins all recognized text into one continuous line, removing any line breaks.
  ```bash
  chrome-lens "https://i.imgur.com/VPd1y6b.png" en --ocr-single-line
  ```

  ---

  **6. Use a SOCKS5 Proxy**
  
  All requests to the Google API will be routed through the specified proxy server, which is useful for privacy or bypassing region restrictions.
  ```bash
  chrome-lens "image.png" --proxy "socks5://127.0.0.1:9050"
  ```

</details>

<details>
  <summary><b>⚙️ Configuration</b></summary>
  
  Settings are loaded with the following priority: **CLI Arguments > `config.json` File > Library Defaults**.
  
  #### **`config.json`**
  
  A `config.json` file can be placed in your system's default config directory to set persistent options.
  -   **Linux**: `~/.config/Chrome-Lens-OCR/config.json`
  -   **macOS**: `~/Library/Application Support/Chrome-Lens-OCR/config.json`
  -   **Windows**: `C:\Users\<user>\.config\Chrome-Lens-OCR\config.json`

  ##### **Example `config.json`**
  ```json
  {
    "api_key": "OPTIONAL! If you don't know what this is, I don't recommend setting it here.",
    "proxy": "socks5://127.0.0.1:9050",
    "client_region": "DE",
    "client_time_zone": "Europe/Berlin",
    "timeout": 90,
    "ocr_preserve_line_breaks": true
  }
  ```

</details>

## Build and Compile Instructions

- Requirements:
    - Python 3.9 or higher

    - Windows:
        - C++ Build Tools (e.g Visual Studio with "Desktop development with C++" kit installed)
        - 7zip (needs to be available from path)

    - Linux:
        - 7zip

- Instructions:

    - Clone the repository to your desired location:
      ```bash
      git clone https://github.com/timminator/Chrome-Lens-OCR.git
      ```
    - Navigate into the cloned folder and install all dependencies:
      ```bash
      cd Chrome-Lens-OCR
      python -m pip install --upgrade pip
      pip install . --group all
      ```
    - Execute the build script to create the desired build:
      ```bash
      python build.py
      ```
    More info can be found via:
    ```bash
    python build.py -h
    ```

### Disclaimer

This project is intended for educational and experimental purposes only. Use of Google's services must comply with their Terms of Service. The author is not responsible for any misuse of this software.
