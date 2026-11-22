from pathlib import Path

# Project root = folder where this script is located
PROJECT_ROOT = Path(__file__).resolve().parent

# Output TXT file
OUTPUT_FILE = PROJECT_ROOT / "project_code.txt"

# Folders we DON'T want to include
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "vlc_64",
    "node_modules",
    ".idea",
    ".vscode",
}

# File extensions that are useful source/config files
IMPORTANT_EXTENSIONS = {
    ".py",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".json",
    ".lua",
    ".spec",
    ".ini",
    ".cfg",
    ".conf",
    ".txt",
    ".srt",
    ".md",
    ".xml",
    ".yaml",
    ".yml",
}

# Specific important files without relying on extension
IMPORTANT_FILES = {
    ".gitignore",
    "requirements.txt",
    "README",
    "README.md",
    "package.json",
    "package-lock.json",
}


def should_include(path: Path):
    # Skip excluded folders
    for part in path.parts:
        if part in EXCLUDED_DIRS:
            return False

    # Skip our output file
    if path.name == OUTPUT_FILE.name:
        return False

    # Include important filenames
    if path.name in IMPORTANT_FILES:
        return True

    # Include selected source extensions
    if path.suffix.lower() in IMPORTANT_EXTENSIONS:
        return True

    return False


def collect_files():
    files = []

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue

        if should_include(path):
            files.append(path)

    return sorted(files)


def main():
    files = collect_files()

    print(f"Project folder: {PROJECT_ROOT}")
    print(f"Found {len(files)} important files.")
    print()

    with open(OUTPUT_FILE, "w", encoding="utf-8", errors="replace") as output:

        output.write("=" * 80 + "\n")
        output.write("PROJECT SOURCE CODE EXPORT\n")
        output.write("=" * 80 + "\n")
        output.write(f"Project: {PROJECT_ROOT.name}\n")
        output.write(f"Files included: {len(files)}\n")
        output.write("=" * 80 + "\n\n")

        for file_path in files:

            relative_path = file_path.relative_to(PROJECT_ROOT)

            print(f"Adding: {relative_path}")

            output.write("\n")
            output.write("#" * 80 + "\n")
            output.write(f"FILE: {relative_path}\n")
            output.write("#" * 80 + "\n\n")

            try:
                content = file_path.read_text(
                    encoding="utf-8",
                    errors="replace"
                )

                output.write(content)
                output.write("\n\n")

            except Exception as e:
                output.write(
                    f"[ERROR READING FILE: {e}]\n\n"
                )

    print()
    print("=" * 80)
    print("DONE!")
    print(f"Output file:")
    print(OUTPUT_FILE)
    print("=" * 80)


if __name__ == "__main__":
    main()