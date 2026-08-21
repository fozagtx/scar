"""Allow `python -m scar.ingest OUT.jsonl --source all`."""

from scar.ingest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
