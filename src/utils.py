"""Utility functions."""

import sys
from typing import Tuple


def check_python_bitness() -> Tuple[bool, str]:
    """
    Check if Python is 32-bit.
    
    Returns:
        Tuple of (is_32bit, message)
    """
    if sys.maxsize > 2**32:
        return False, f"Python is 64-bit (maxsize={sys.maxsize}). FSUIPC requires 32-bit Python."
    else:
        return True, f"Python is 32-bit (maxsize={sys.maxsize})."


def require_32bit_python() -> None:
    """
    Require 32-bit Python. Raises RuntimeError if not 32-bit.
    
    This is a hard constraint for FSUIPC integration.
    """
    is_32bit, message = check_python_bitness()
    if not is_32bit:
        raise RuntimeError(
            f"FATAL: {message}\n"
            "FSX Weather Bridge requires 32-bit Python to work with FSUIPC.\n"
            "Please install Python 32-bit from python.org/downloads/"
        )


def nm_to_km(nm: float) -> float:
    """Convert nautical miles to kilometers."""
    return nm * 1.852


def km_to_nm(km: float) -> float:
    """Convert kilometers to nautical miles."""
    return km / 1.852


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great circle distance between two points in nautical miles.
    
    Args:
        lat1, lon1: First point (degrees)
        lat2, lon2: Second point (degrees)
    
    Returns:
        Distance in nautical miles
    """
    import math
    
    R_km = 6371.0  # Earth radius in km
    R_nm = R_km / 1.852  # Earth radius in nm
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    
    return R_nm * c
