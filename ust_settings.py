import os

# ============================================================
# CONFIGURATION
# ============================================================
MAX_TRANSLATION_WORKERS = 8
MAX_CHARS_PER_CHUNK = 3000
VLC_ORANGE = "#ff8c00"
DARK_BG = "#121212"
PANEL_BG = "#1e1e1e"

AUDIO_SEGMENT_TIME      = 300   # 5-min chunks — better parallelism with 4 workers
MAX_TRANSCRIPTION_WORKERS = 4   # parallel chunk transcription
TRANSLATION_BATCH_SIZE  = 15

# ============================================================
# .VSUB CLOUD SERVER  —  proxy that holds your API keys
# ============================================================
# Set this to your deployed server URL after deploying server/server.py.
# Leave VSUB_CLOUD_TOKEN empty if the server has no SECRET set.
VSUB_CLOUD_URL   = "https://vlc-sub.onrender.com/transcribe"
VSUB_CLOUD_TOKEN = ""   # set if you added VSUB_SECRET on the server

# ============================================================
# DIRECTORY SETUP
# ============================================================
try:
    if os.name == 'nt' and os.getenv('APPDATA'):
        BASE_DIR = os.path.join(os.getenv('APPDATA'), 'Vsub')
    else:
        BASE_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'Vsub')
    TEMP_DIR = os.path.join(BASE_DIR, "temp_audio")
    SUB_DIR  = os.path.join(BASE_DIR, "subtitles")
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(SUB_DIR,  exist_ok=True)
except Exception:
    TEMP_DIR = os.path.join(os.getcwd(), "temp_audio")
    SUB_DIR  = os.path.join(os.getcwd(), "subtitles")
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(SUB_DIR,  exist_ok=True)

# ============================================================
# LANGUAGE DICTIONARIES
# ============================================================
LANGUAGES = {
    "Afrikaans": "af", "Albanian": "sq", "Amharic": "am", "Arabic": "ar",
    "Armenian": "hy", "Azerbaijani": "az", "Basque": "eu", "Belarusian": "be",
    "Bengali": "bn", "Bosnian": "bs", "Bulgarian": "bg", "Catalan": "ca",
    "Cebuano": "ceb", "Chinese (Simplified)": "zh-CN", "Chinese (Traditional)": "zh-TW",
    "Croatian": "hr", "Czech": "cs", "Danish": "da", "Dutch": "nl", "English": "en",
    "Estonian": "et", "Filipino": "tl", "Finnish": "fi", "French": "fr", "Georgian": "ka",
    "German": "de", "Greek": "el", "Gujarati": "gu", "Hebrew": "he", "Hindi": "hi",
    "Hungarian": "hu", "Icelandic": "is", "Indonesian": "id", "Irish": "ga", "Italian": "it",
    "Japanese": "ja", "Javanese": "jv", "Kannada": "kn", "Kazakh": "kk", "Khmer": "km",
    "Korean": "ko", "Latin": "la", "Latvian": "lv", "Lithuanian": "lt", "Macedonian": "mk",
    "Malay": "ms", "Malayalam": "ml", "Marathi": "mr", "Mongolian": "mn", "Nepali": "ne",
    "Norwegian": "no", "Persian": "fa", "Polish": "pl", "Portuguese": "pt", "Punjabi": "pa",
    "Romanian": "ro", "Russian": "ru", "Serbian": "sr", "Sinhala": "si", "Slovak": "sk",
    "Slovenian": "sl", "Spanish": "es", "Swahili": "sw", "Swedish": "sv", "Tamil": "ta",
    "Telugu": "te", "Thai": "th", "Turkish": "tr", "Ukrainian": "uk", "Urdu": "ur",
    "Vietnamese": "vi", "Welsh": "cy"
}

WHISPER_LANGUAGES = {
    "Auto Detect (Recommended)": None,
    "Afrikaans": "af", "Arabic": "ar", "Armenian": "hy", "Azerbaijani": "az",
    "Belarusian": "be", "Bosnian": "bs", "Bulgarian": "bg", "Catalan": "ca",
    "Chinese": "zh", "Croatian": "hr", "Czech": "cs", "Danish": "da",
    "Dutch": "nl", "English": "en", "Estonian": "et", "Finnish": "fi",
    "French": "fr", "Galician": "gl", "German": "de", "Greek": "el",
    "Hebrew": "he", "Hindi": "hi", "Hungarian": "hu", "Icelandic": "is",
    "Indonesian": "id", "Italian": "it", "Japanese": "ja", "Kannada": "kn",
    "Kazakh": "kk", "Korean": "ko", "Latvian": "lv", "Lithuanian": "lt",
    "Macedonian": "mk", "Malay": "ms", "Malayalam": "ml", "Marathi": "mr",
    "Maori": "mi", "Nepali": "ne", "Norwegian": "no", "Persian": "fa",
    "Polish": "pl", "Portuguese": "pt", "Romanian": "ro", "Russian": "ru",
    "Serbian": "sr", "Slovak": "sk", "Slovenian": "sl", "Spanish": "es",
    "Swahili": "sw", "Swedish": "sv", "Tagalog": "tl", "Tamil": "ta",
    "Telugu": "te", "Thai": "th", "Turkish": "tr", "Ukrainian": "uk",
    "Urdu": "ur", "Vietnamese": "vi", "Welsh": "cy", "Yoruba": "yo"
}

COMMON_FONTS = [
    "Arial", "Segoe UI", "Calibri", "Verdana", "Tahoma", "Trebuchet MS",
    "Times New Roman", "Georgia", "Courier New", "Impact", "Comic Sans MS",
    "Helvetica Neue", "Open Sans", "Roboto", "Ubuntu"
]

# ============================================================
# SUBTITLE STYLE TEMPLATES
# ============================================================
STYLE_TEMPLATES = {
    "Default (White + Outline)": {
        "font_name": "Arial", "font_size": 20,
        "primary_color": "#FFFFFF", "outline_color": "#000000",
        "background": True, "bold": False, "italic": False,
        "outline": 2, "shadow": 1, "position": "bottom",
    },
    "Cinema Bold": {
        "font_name": "Impact", "font_size": 26,
        "primary_color": "#FFFF00", "outline_color": "#000000",
        "background": False, "bold": True, "italic": False,
        "outline": 3, "shadow": 2, "position": "bottom",
    },
    "Netflix Style": {
        "font_name": "Arial", "font_size": 22,
        "primary_color": "#FFFFFF", "outline_color": "#000000",
        "background": True, "bold": False, "italic": False,
        "outline": 1, "shadow": 0, "position": "bottom",
    },
    "Neon Green": {
        "font_name": "Verdana", "font_size": 20,
        "primary_color": "#00FF7F", "outline_color": "#003300",
        "background": False, "bold": True, "italic": False,
        "outline": 2, "shadow": 1, "position": "bottom",
    },
    "Classic Yellow": {
        "font_name": "Arial", "font_size": 22,
        "primary_color": "#FFFF00", "outline_color": "#000000",
        "background": False, "bold": False, "italic": False,
        "outline": 2, "shadow": 0, "position": "bottom",
    },
    "Elegant Italic": {
        "font_name": "Georgia", "font_size": 20,
        "primary_color": "#FFFFFF", "outline_color": "#330000",
        "background": True, "bold": False, "italic": True,
        "outline": 1, "shadow": 1, "position": "bottom",
    },
    "Top Title": {
        "font_name": "Segoe UI", "font_size": 20,
        "primary_color": "#FFFFFF", "outline_color": "#000000",
        "background": True, "bold": True, "italic": False,
        "outline": 2, "shadow": 1, "position": "top",
    },
    "Minimal Clean": {
        "font_name": "Calibri", "font_size": 18,
        "primary_color": "#FFFFFF", "outline_color": "#000000",
        "background": False, "bold": False, "italic": False,
        "outline": 1, "shadow": 0, "position": "bottom",
    },
    "Documentary": {
        "font_name": "Trebuchet MS", "font_size": 19,
        "primary_color": "#F0E68C", "outline_color": "#000000",
        "background": True, "bold": False, "italic": False,
        "outline": 2, "shadow": 1, "position": "bottom",
    },
    "Horror / Dark": {
        "font_name": "Courier New", "font_size": 20,
        "primary_color": "#FF3030", "outline_color": "#000000",
        "background": True, "bold": True, "italic": False,
        "outline": 3, "shadow": 2, "position": "bottom",
    },
}