"""Allow ``python -m scar``."""

from scar.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
