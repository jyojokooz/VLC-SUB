import os

# Configuration
OUTPUT_FILE = 'file.txt'

# Add or remove file extensions you consider "important"
ALLOWED_EXTENSIONS = {'.py', '.html', '.css', '.js', '.iss', '.spec', '.gitignore'}

# Folders to completely ignore (like build artifacts and assets)
IGNORED_DIRS = {'__pycache__', 'build', 'dist', 'assets', 'Output', 'subtitles', 'downloads', '.git', '_internal'}

def combine_files():
    # Open the output file in write mode
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        
        # Walk through the directory tree starting from the current folder ('.')
        for root, dirs, files in os.walk('.'):
            
            # Modify the 'dirs' list in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            
            for file in files:
                # Prevent the script from reading its own output file
                if file == OUTPUT_FILE:
                    continue
                
                # Get the file extension
                _, ext = os.path.splitext(file)
                ext = ext.lower()
                
                # Special check for files like .gitignore where the whole name is considered the extension by splitext
                is_important = (ext in ALLOWED_EXTENSIONS) or (file in ALLOWED_EXTENSIONS)
                
                if is_important:
                    filepath = os.path.join(root, file)
                    
                    try:
                        # Read the content of the source file
                        with open(filepath, 'r', encoding='utf-8') as infile:
                            content = infile.read()
                            
                        # Write a nice separator, the file name, and the content to the txt
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