"""Patch main.py: add .Vsub Cloud validation logic to run_generation()"""
import re

path = r"c:\VLC-SUB\main.py"
content = open(path, encoding="utf-8").read()

OLD = (
    '    if not _require(api_key, "❌ API Key Missing",\n'
    '                    "Please enter your API key.\\n\\n"\n'
    '                    "• Groq (Free): Get a key at https://console.groq.com\\n"\n'
    '                    "• OpenAI: Get a key at https://platform.openai.com\\n\\n"\n'
    '                    "Paste the key in the API Key field, then click 💾 Save."):\n'
    '        return\n'
    '    if "Custom" in provider and not _require(\n'
    '            custom_url.startswith("http"), "❌ Invalid Custom URL",\n'
    '            "Custom API URL must start with http:// or https://\\n\\n"\n'
    '            "Example: https://api.openai.com/v1/audio/transcriptions"):\n'
    '        return\n'
    '\n'
    '    save_api_key(api_key)\n'
)

NEW = (
    '    # ── .Vsub Cloud: proxy server holds the API keys — user needs nothing ──\n'
    '    _using_cloud = ".Vsub Cloud" in provider\n'
    '    if _using_cloud:\n'
    '        # Redirect to the .Vsub backend proxy\n'
    '        provider   = "Custom API (OpenAI Format)"\n'
    '        custom_url = config.VSUB_CLOUD_URL\n'
    '        api_key    = config.VSUB_CLOUD_TOKEN   # empty string = open server\n'
    '    else:\n'
    '        if not _require(api_key, "❌ API Key Missing",\n'
    '                        "Please enter your API key.\\n\\n"\n'
    '                        "• Groq (Free): Get a key at https://console.groq.com\\n"\n'
    '                        "• OpenAI: Get a key at https://platform.openai.com\\n\\n"\n'
    '                        "Paste the key in the API Key field, then click 💾 Save."):\n'
    '            return\n'
    '        if "Custom" in provider and not _require(\n'
    '                custom_url.startswith("http"), "❌ Invalid Custom URL",\n'
    '                "Custom API URL must start with http:// or https://\\n\\n"\n'
    '                "Example: https://api.openai.com/v1/audio/transcriptions"):\n'
    '            return\n'
    '        save_api_key(api_key)\n'
)

if OLD not in content:
    print("ERROR: target block not found!")
    raise SystemExit(1)

content = content.replace(OLD, NEW, 1)
open(path, "w", encoding="utf-8").write(content)
print("Patched OK")
