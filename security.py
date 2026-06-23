import keyring
import os
import base64

SERVICE_NAME = "UniversalSubtitleToolkit"
ACCOUNT_NAME = "api_key_secure_storage"

# Fallback path if Windows Vault is blocked
try:
    FALLBACK_FILE = os.path.join(os.getenv('APPDATA'), 'UniversalSubtitles', '.secure_key')
except Exception:
    FALLBACK_FILE = os.path.join(os.getcwd(), '.secure_key')

def save_api_key(api_key):
    """Saves the API key securely."""
    if api_key and api_key.strip():
        try:
            # Try Windows Credential Manager first
            keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, api_key.strip())
        except Exception:
            # Fallback: Base64 obfuscated file in AppData
            os.makedirs(os.path.dirname(FALLBACK_FILE), exist_ok=True)
            with open(FALLBACK_FILE, "wb") as f:
                f.write(base64.b64encode(api_key.strip().encode()))

def load_api_key():
    """Retrieves the API key securely."""
    try:
        key = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
        if key: return key
    except Exception:
        pass
    
    # Check fallback if Windows vault failed
    if os.path.exists(FALLBACK_FILE):
        try:
            with open(FALLBACK_FILE, "rb") as f:
                return base64.b64decode(f.read()).decode()
        except Exception:
            pass
            
    return ""