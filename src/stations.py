"""Station database management."""

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.utils import haversine_distance


class Station:
    """Represents a weather station."""
    
    def __init__(self, icao: str, lat: float, lon: float, name: str, country: str):
        self.icao = icao.upper()
        self.lat = float(lat)
        self.lon = float(lon)
        self.name = name
        self.country = country
    
    def distance_to(self, lat: float, lon: float) -> float:
        """Calculate distance to a point in nautical miles."""
        return haversine_distance(self.lat, self.lon, lat, lon)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "icao": self.icao,
            "lat": self.lat,
            "lon": self.lon,
            "name": self.name,
            "country": self.country,
        }


class StationDatabase:
    """Manages the station database."""
    
    def __init__(self, csv_path: Optional[Path] = None):
        """
        Initialize station database.
        
        Args:
            csv_path: Path to stations CSV file. If None, uses default location.
        """
        if csv_path is None:
            csv_path = Path(__file__).parent.parent / "data" / "stations.csv"
        
        self.csv_path = Path(csv_path)
        self.stations: Dict[str, Station] = {}
        self._load()
    
    def _load(self) -> None:
        """Load stations from CSV file."""
        if not self.csv_path.exists():
            # Create empty database if file doesn't exist
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            return
        
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    icao = row.get("icao", "").strip().upper()
                    if not icao:
                        continue
                    
                    station = Station(
                        icao=icao,
                        lat=float(row.get("lat", 0)),
                        lon=float(row.get("lon", 0)),
                        name=row.get("name", "").strip(),
                        country=row.get("country", "").strip(),
                    )
                    self.stations[icao] = station
                except (ValueError, KeyError) as e:
                    # Skip invalid rows
                    continue
    
    def get_station(self, icao: str) -> Optional[Station]:
        """Get station by ICAO code."""
        return self.stations.get(icao.upper())
    
    def find_nearest_stations(
        self,
        lat: float,
        lon: float,
        radius_nm: float = 50.0,
        max_results: int = 3,
        fallback_to_global: bool = True,
    ) -> List[Tuple[Station, float]]:
        """
        Find nearest stations within radius.
        
        Args:
            lat, lon: Search center (degrees)
            radius_nm: Search radius in nautical miles
            max_results: Maximum number of results
            fallback_to_global: If True and no stations found, return nearest globally
        
        Returns:
            List of (Station, distance_nm) tuples, sorted by distance
        """
        results: List[Tuple[Station, float]] = []
        
        for station in self.stations.values():
            distance = station.distance_to(lat, lon)
            if distance <= radius_nm:
                results.append((station, distance))
        
        # Sort by distance
        results.sort(key=lambda x: x[1])
        
        # Limit results
        results = results[:max_results]
        
        # Fallback to global nearest if no results and fallback enabled
        if not results and fallback_to_global:
            all_distances = [
                (station, station.distance_to(lat, lon))
                for station in self.stations.values()
            ]
            if all_distances:
                all_distances.sort(key=lambda x: x[1])
                results = all_distances[:max_results]
        
        return results
    
    def get_all_stations(self) -> List[Station]:
        """Get all stations."""
        return list(self.stations.values())
    
    def to_geojson(self) -> dict:
        """Convert all stations to GeoJSON format."""
        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [station.lon, station.lat],
                },
                "properties": {
                    "icao": station.icao,
                    "name": station.name,
                    "country": station.country,
                },
            }
            for station in self.stations.values()
        ]
        
        return {
            "type": "FeatureCollection",
            "features": features,
        }
