import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union

from _version import __version__

# --- Configuration ---
APP_VERSION = __version__


# --- Helper Functions ---
def print_header(message: str) -> None:
    """Prints a formatted header."""
    print("\n" + "=" * 60)
    print(f" {message}")
    print("=" * 60)


def check_7zip() -> None:
    """Checks if 7-Zip is installed and available."""
    print_header("Checking for 7-Zip...")
    if not (shutil.which("7z") or shutil.which("7z.exe")):
        print("ERROR: 7-Zip executable ('7z' or '7z.exe') not found in your system's PATH.")
        print("Please install 7-Zip and ensure it's added to your PATH.")
        sys.exit(1)
    print("7-Zip found.")


def run_command(command: list[str], cwd: Optional[Union[str, Path]] = None) -> None:
    """Runs a command in the shell, streams its output, and exits if it fails."""
    try:
        print(f"\nRunning command: {' '.join(command)}" + (f" in '{cwd}'" if cwd else ""))
        subprocess.run(command, check=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Command failed with exit code {e.returncode}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"ERROR: Command '{command[0]}' not found. Is it in your PATH?")
        sys.exit(1)


def sign_file(signtool_path: Optional[str], cert_name: Optional[str], file_to_sign: Path) -> None:
    """Signs a file using signtool.exe on Windows."""
    if not signtool_path or sys.platform != "win32":
        return

    print_header(f"Signing {file_to_sign.name}...")
    if not Path(signtool_path).is_file():
        print(f"ERROR: Sign tool not found at '{signtool_path}'")
        sys.exit(1)

    command = [signtool_path, "sign", "/tr", "http://timestamp.digicert.com", "/td", "sha256", "/fd", "sha256"]
    if cert_name:
        command.extend(["/n", cert_name])
    else:
        command.append("/a")

    command.append(str(file_to_sign))
    run_command(command)
    print(f"Successfully signed {file_to_sign.name}")


def create_final_archive(folder_path: Path) -> None:
    """Creates a compressed archive of the final build folder."""
    print_header(f"Creating final archive for {folder_path.name}")

    try:
        seven_zip_exe = shutil.which("7z") or shutil.which("7z.exe")
        if not seven_zip_exe:
            print("WARNING: 7-Zip not found, cannot create .7z archive. Skipping.")
            return

        archive_path = folder_path.parent / f"{folder_path.name}.7z"
        print(f"Creating {archive_path.name}...")

        command = [
            seven_zip_exe,
            "a",
            "-t7z",
            "-mx=9",
            "-m0=lzma2",
            "-md=64m",
            "-mfb=64",
            "-ms=on",
            str(archive_path.name),
            str(folder_path.name),
        ]

        run_command(command, cwd=str(folder_path.parent))
        print(f"Archive created successfully: {archive_path}")

    except Exception as e:
        print(f"ERROR: Failed to create archive. Reason: {e}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chrome Lens OCR Build Script")
    parser.add_argument("--signtool", default=None, help="(Optional, Windows only) Path to signtool.exe for code signing.")
    parser.add_argument(
        "--sign-cert-name", default=None, help="(Optional, Windows only) The subject name of the certificate to use for signing."
    )
    parser.add_argument(
        "--archive", default="false", help="(Optional) Set to 'true' to create a compressed .7z archive of the final build folder."
    )
    parser.add_argument(
        "--release-type",
        default=None,
        help="(Optional) Specify a release type (e.g., 'Beta', 'RC1') to append to the output artifact names.",
    )
    args = parser.parse_args()

    if args.archive.lower() == "true":
        check_7zip()

    releases_dir = Path("Releases")
    if releases_dir.exists():
        print_header("Cleaning previous build artifacts")
        print(f"Removing existing directory: {releases_dir}")
        shutil.rmtree(releases_dir)
    releases_dir.mkdir(exist_ok=True)

    print_header("Compiling Binary with Nuitka")

    dist_folder = Path("chrome_lens_ocr.dist")
    if dist_folder.exists():
        shutil.rmtree(dist_folder)

    # Nuitka compilation
    run_command([sys.executable, "-m", "nuitka", "chrome_lens_ocr.py"])

    if not dist_folder.is_dir():
        print(f"ERROR: Nuitka failed to create the dist folder: {dist_folder}")
        sys.exit(1)

    os_suffix = "-Linux" if sys.platform != "win32" else ""
    release_tag = f"-{args.release_type}" if args.release_type else ""
    final_folder_name = f"Chrome-Lens-OCR-v{APP_VERSION}{release_tag}{os_suffix}"
    final_app_path = releases_dir / final_folder_name

    print(f"\nMoving compiled files to '{final_app_path}'")
    shutil.move(str(dist_folder), final_app_path)

    # Signing
    exe_name = "chrome-lens.exe" if sys.platform == "win32" else "chrome-lens.bin"
    executable_path = final_app_path / exe_name
    if executable_path.exists():
        sign_file(args.signtool, args.sign_cert_name, executable_path)
    else:
        print(f"WARNING: Expected executable not found at {executable_path}")

    # Archiving
    if args.archive.lower() == "true":
        create_final_archive(final_app_path)

    print_header("Build Complete!")
    print(f"Outputs are located in the '{releases_dir}' folder.")


if __name__ == "__main__":
    main()
