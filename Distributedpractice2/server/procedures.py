"""Remote procedures exposed by the server.

Each function is plain Python: it knows nothing about sockets or JSON.
Arguments and return values must be JSON-compatible.
"""

from __future__ import annotations

import platform
import socket
import sys
import time
from datetime import datetime, timezone

# ----------------------------------------------------------------------
# Procedures provided by the instructor
# ----------------------------------------------------------------------


def add(a, b):
    """Return a + b."""
    return a + b


def multiply(a, b):
    """Return a * b."""
    return a * b


def power(a, b):
    """Return a ** b."""
    return a ** b


def slow_task(seconds):
    """Sleep for `seconds` and return them. Useful for checking concurrency."""
    time.sleep(seconds)
    return seconds


# ----------------------------------------------------------------------
# Additional procedures (student design)
# ----------------------------------------------------------------------

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FORMAT = "JPEG"


def image_info(name: str) -> dict:
    """Return the metadata of an image.

    Args:
        name: Name of the image file.

    Returns:
        Dictionary with the filename, dimensions and format.
    """
    return {
        "file": name,
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
        "format": DEFAULT_FORMAT,
    }


def grayscale(name: str) -> str:
    """Convert an image to grayscale.

    Args:
        name: Name of the image file.

    Returns:
        Message describing the result of the processing.
    """
    return f"{name} converted to grayscale"


def resize(name: str, width: int, height: int) -> dict:
    """Resize an image to the given dimensions.

    Args:
        name: Name of the image file.
        width: Target width in pixels.
        height: Target height in pixels.

    Returns:
        Dictionary with the file name and the resulting dimensions.
    """
    return {"file": name, "width": width, "height": height}


def server_info() -> dict:
    """Describe the machine that executes the procedures (hostname, OS, Python, UTC time)."""
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "utc_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


MAX_FACTORIZABLE = 10**12  # trial division needs at most ~1e6 steps


def prime_factors(n: int) -> list:
    """Return the prime factorisation of n as a sorted list (e.g. 360 -> [2, 2, 2, 3, 3, 5])."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an integer")
    if not 2 <= n <= MAX_FACTORIZABLE:
        raise ValueError(f"n must be between 2 and {MAX_FACTORIZABLE}")

    factors = []
    divisor = 2
    while divisor * divisor <= n:
        while n % divisor == 0:
            factors.append(divisor)
            n //= divisor
        divisor += 1 if divisor == 2 else 2
    if n > 1:
        factors.append(n)
    return factors
