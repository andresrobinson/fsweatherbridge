"""Tests for station database."""

import unittest
from pathlib import Path

from src.stations import Station, StationDatabase


class TestStations(unittest.TestCase):
    """Test station database."""
    
    def test_station_creation(self):
        """Test creating a station."""
        station = Station("KJFK", 40.6398, -73.7789, "JFK", "US")
        
        self.assertEqual(station.icao, "KJFK")
        self.assertEqual(station.lat, 40.6398)
        self.assertEqual(station.lon, -73.7789)
        self.assertEqual(station.name, "JFK")
        self.assertEqual(station.country, "US")
    
    def test_station_distance(self):
        """Test station distance calculation."""
        station1 = Station("KJFK", 40.6398, -73.7789, "JFK", "US")
        station2 = Station("KLAX", 33.9425, -118.4081, "LAX", "US")
        
        distance = station1.distance_to(station2.lat, station2.lon)
        
        # Should be approximately 2450 NM
        self.assertGreater(distance, 2300)
        self.assertLess(distance, 2600)
    
    def test_station_database_load(self):
        """Test loading station database."""
        # Use test data
        csv_path = Path(__file__).parent.parent / "data" / "stations.csv"
        if csv_path.exists():
            db = StationDatabase(csv_path)
            
            # Should have loaded some stations
            self.assertGreater(len(db.stations), 0)
            
            # Test getting a station
            station = db.get_station("KJFK")
            if station:
                self.assertEqual(station.icao, "KJFK")
    
    def test_find_nearest_stations(self):
        """Test finding nearest stations."""
        csv_path = Path(__file__).parent.parent / "data" / "stations.csv"
        if csv_path.exists():
            db = StationDatabase(csv_path)
            
            # Find stations near New York
            results = db.find_nearest_stations(40.7128, -74.0060, radius_nm=100.0, max_results=3)
            
            # Should find at least one station
            self.assertGreater(len(results), 0)
            
            # Results should be sorted by distance
            for i in range(len(results) - 1):
                self.assertLessEqual(results[i][1], results[i + 1][1])
