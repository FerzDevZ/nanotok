"""Allow ``python -m nanotok``."""

from nanotok.cli import entrypoint

if __name__ == "__main__":
    raise SystemExit(entrypoint())
