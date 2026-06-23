import os

# ============================================================
# CONFIGURATION
# ============================================================
MAX_TRANSLATION_WORKERS = 8
MAX_CHARS_PER_CHUNK = 3000
VLC_ORANGE = "#ff8c00"
DARK_BG = "#121212"
PANEL_BG = "#1e1e1e"

# ============================================================
# DIRECTORY SETUP
# ============================================================
try:
    if os.name == 'nt' and os.getenv('APPDATA'):
        BASE_DIR = os.path.join(os.getenv('APPDATA'), 'UniversalSubtitles')
    else:
        BASE_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'UniversalSubtitles')
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