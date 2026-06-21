"""Helper to download the full Malloy hook catalog."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shortmaker.hooks import fetch_all  # noqa: E402


def main() -> None:
    print("Fetching all Malloy hooks...")
    paths = fetch_all()
    print(f"Cached {len(paths)} hooks in assets/hooks/")


if __name__ == "__main__":
    main()