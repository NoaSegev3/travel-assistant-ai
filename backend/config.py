# Role: Central configuration module. Loads .env into environment variables and computes runtime flags (DEBUG).
# Importers read backend.config.DEBUG to control logging without threading flags through every call.

from __future__ import annotations

import os
from dotenv import load_dotenv

DEBUG: bool = False


def load_env() -> None:
    """
    Load .env into os.environ, then recompute DEBUG.
    This makes DEBUG correct even if load_env() is called after import.
    """
    global DEBUG
    load_dotenv()
    # Key line: accept common truthy values.
    DEBUG = os.getenv("DEBUG", "0").lower() in {"1", "true", "yes"}
