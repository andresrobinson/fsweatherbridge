"""Tests for utility functions."""

import sys
import unittest

from src.utils import check_python_bitness, haversine_distance, require_32bit_python


class TestUtils(unittest.TestCase):
    """Test utility functions."""
    
    def test_check_python_bitness(self):
        """Test Python bitness check."""
        is_32bit, message = check_python_bitness()
        self.assertIsInstance(is_32bit, bool)
        self.assertIsInstance(message, str)
    
    def test_haversine_distance(self):
        """Test haversine distance calculation."""
        # Distance between New York and Los Angeles (approximately 2450 NM)
        ny_lat, ny_lon = 40.7128, -74.0060
        la_lat, la_lon = 34.0522, -118.2437
        
        distance = haversine_distance(ny_lat, ny_lon, la_lat, la_lon)
        
        # Should be approximately 2450 NM (allow 5% error)
        self.assertGreater(distance, 2300)
        self.assertLess(distance, 2600)
        
        # Same point should be 0
        self.assertAlmostEqual(haversine_distance(ny_lat, ny_lon, ny_lat, ny_lon), 0.0, places=1)


class TestBitnessGuard(unittest.TestCase):
    """Test bitness guard."""
    
    def test_require_32bit_python_64bit(self):
        """Test that 64-bit Python raises error."""
        if sys.maxsize > 2**32:
            # We're on 64-bit Python
            with self.assertRaises(RuntimeError):
                require_32bit_python()
        else:
            # We're on 32-bit Python, should not raise
            try:
                require_32bit_python()
            except RuntimeError:
                self.fail("require_32bit_python() raised RuntimeError on 32-bit Python")
