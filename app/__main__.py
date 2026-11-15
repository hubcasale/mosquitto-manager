"""Entry point: ``python -m app``."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from .config import ConfigError, Settings
from .main import create_app


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(2)

    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_app(settings),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        log_level=settings.log_level,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
