import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
scripts = root / "scripts"
sys.path.insert(0, str(scripts))
