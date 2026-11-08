"""Central configuration. Works the same locally, on Colab, Kaggle or HF Spaces."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()

# One sub-folder per exam year: data/2022, data/2023, ...
DATA_DIR = Path(os.getenv("BAC_DATA_DIR", BASE_DIR / "data"))
CACHE_DIR = Path(os.getenv("BAC_CACHE_DIR", BASE_DIR / ".cache"))

# Verify exact names available to your key with client.models.list()
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gemini-3.5-flash")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "gemini-3.8-flash")
# Backup models used when the main one is overloaded (comma separated in the env var).
# By default each role falls back to the other role's model. Use names your key can access.
GENERATOR_FALLBACKS = [x.strip() for x in os.getenv("GENERATOR_FALLBACKS", ROUTER_MODEL).split(",") if x.strip()]
ROUTER_FALLBACKS = [x.strip() for x in os.getenv("ROUTER_FALLBACKS", GENERATOR_MODEL).split(",") if x.strip()]


def get_api_key() -> str:
    """Env var first, then Kaggle / Colab secrets as a fallback."""
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    try:
        from kaggle_secrets import UserSecretsClient
        return UserSecretsClient().get_secret("GEMINI_API_KEY")
    except Exception:
        pass
    try:
        from google.colab import userdata
        return userdata.get("GEMINI_API_KEY")
    except Exception:
        pass
    raise RuntimeError("GEMINI_API_KEY not found. Set it as an env variable or in .env")
