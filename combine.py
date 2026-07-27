import os

# Configuration
OUTPUT_FILE = 'file.txt'

# Add or remove file extensions you consider "important"
ALLOWED_EXTENSIONS = {'.py', '.html', '.css', '.js', '.iss', '.spec', '.gitignore', '.json', '.md'}

# Folders to completely ignore (build artifacts, envs, deps, assets, etc.)
IGNORED_DIRS = {
    '__pycache__', 'build', 'dist', 'assets', 'Output', 'subtitles',
    'downloads', '.git', '_internal', '.venv', 'venv', 'env',
    'site-packages', 'node_modules', '.idea', '.vscode', 'egg-info'
}

# Exact filenames to skip even if extension matches
IGNORED_FILES = {OUTPUT_FILE, 'combine.py'}

def combine_files():
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:

        for root, dirs, files in os.walk('.'):

            # Skip ignored dirs (also catches any dir containing these names, e.g. .venv/Lib/site-packages)
            dirs[:] = [
                d for d in dirs
                if d not in IGNORED_DIRS and not any(ig in os.path.join(root, d) for ig in IGNORED_DIRS)
            ]

            for file in files:
                if file in IGNORED_FILES:
                    continue

                _, ext = os.path.splitext(file)
                ext = ext.lower()

                is_important = (ext in ALLOWED_EXTENSIONS) or (file in ALLOWED_EXTENSIONS)

                if is_important:
                    filepath = os.path.join(root, file)

                    try:
                        with open(filepath, 'r', encoding='utf-8') as infile:
                            content = infile.read()

                        outfile.write(f"{'='*60}\n")
                        outfile.write(f"FILE: {filepath}\n")
                        outfile.write(f"{'='*60}\n\n")
                        outfile.write(content)
                        outfile.write("\n\n")

                        print(f"Added: {filepath}")

                    except Exception as e:
                        print(f"Skipped {filepath} (Error: {e})")

    print(f"\nDone! All important files have been combined into '{OUTPUT_FILE}'.")

if __name__ == "__main__":
    combine_files()