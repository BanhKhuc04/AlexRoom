import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VERSION_FILE = BASE_DIR / "VERSION"

SEMVER_REGEX = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

def _load_version() -> str:
    if not VERSION_FILE.exists():
        raise RuntimeError(f"Cannot find canonical version file: {VERSION_FILE}")
    
    version = VERSION_FILE.read_text("utf-8").strip()
    
    if not version:
        raise ValueError("VERSION file is empty")
        
    if not SEMVER_REGEX.match(version):
        raise ValueError(f"Invalid semantic version format in VERSION file: '{version}'")
        
    return version

ALEX_VERSION = _load_version()
