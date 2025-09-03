# Compilation instructions
# nuitka-project: --standalone

# nuitka-project-if: {OS} == "Windows":
#     nuitka-project: --output-filename=chrome-lens-cli
# nuitka-project-if: {OS} == "Linux":
#     nuitka-project: --output-filename=chrome-lens-cli.bin

# Windows-specific metadata for the executable
# nuitka-project-if: {OS} == "Windows":
#     nuitka-project: --file-description="Chrome Lens CLI"
#     nuitka-project: --file-version="3.3.0"
#     nuitka-project: --product-name="Chrome-Lens-CLI"
#     nuitka-project: --product-version="3.3.0"
#     nuitka-project: --copyright="timminator"

import sys

from chrome_lens_py.cli.main import run

if __name__ == "__main__":
    if len(sys.argv) == 1: 
        sys.argv.append("--help") 
    run()
