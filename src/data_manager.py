"""Data persistence manager for stations and weather data."""

import asyncio
import gzip
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp

# Try to import airportsdata for airport name lookup
try:
    import airportsdata
    AIRPORTS_DATA_AVAILABLE = True
    airports_db = None  # Will be loaded on first use
except ImportError:
    AIRPORTS_DATA_AVAILABLE = False
    airports_db = None

logger = logging.getLogger(__name__)


class DataManager:
    """Manages persistent storage of stations and weather data."""
    
    BASE_URL = "https://aviationweather.gov/api/data"
    CACHE_URL = "https://aviationweather.gov/data/cache"
    AIRPORT_API_URL = f"{BASE_URL}/airport"
    DATA_DIR = Path(__file__).parent.parent / "data"
    
    # File paths
    STATIONS_FILE = DATA_DIR / "stations_full.json"
    METAR_FILE = DATA_DIR / "metar_latest.json"
    TAF_FILE = DATA_DIR / "taf_latest.json"
    METAR_ARCHIVE_DIR = DATA_DIR / "metar_archive"
    TAF_ARCHIVE_DIR = DATA_DIR / "taf_archive"
    AIRPORT_DATA_FILE = DATA_DIR / "airport_data.json"  # Local cache of airport data from AviationWeather.gov
    AIRPORTS_CSV_FILE = DATA_DIR / "airports.csv"  # Local airports.csv file (from airportsdata project)
    AIRPORTS_CSV_FILE = DATA_DIR / "airports.csv"  # Local airports.csv file (from airportsdata project)
    
    # Station list cache duration (24 hours)
    STATIONS_CACHE_HOURS = 24
    # Weather data refresh interval (1 hour)
    WEATHER_REFRESH_HOURS = 1
    # Airport data update interval (7 days = 168 hours)
    AIRPORT_DATA_CACHE_HOURS = 168
    
    def __init__(self):
        """Initialize data manager."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.METAR_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        self.TAF_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        self.airport_data_cache: Optional[Dict[str, Dict]] = None  # Lazy-loaded airport data cache
        self.airports_csv_cache: Optional[Dict[str, Dict]] = None  # Lazy-loaded airports.csv cache
    
    async def download_full_stations(self) -> List[Dict]:
        """
        Download full list of stations/airports from AviationWeather.gov cache file.
        
        Returns:
            List of station dictionaries with icao, lat, lon, name, country
        """
        logger.info("Downloading full station list from AviationWeather.gov...")
        stations = []
        
        try:
            # Use the stations cache file which contains ALL stations worldwide
            # Updated once per day according to API docs
            async with aiohttp.ClientSession() as session:
                # Try JSON format first (easier to parse)
                url = f"{self.CACHE_URL}/stations.cache.json.gz"
                
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as response:
                    if response.status == 200:
                        # Decompress gzipped data
                        compressed_data = await response.read()
                        decompressed_data = gzip.decompress(compressed_data)
                        text = decompressed_data.decode('utf-8')
                        
                        # Parse JSON
                        try:
                            data = json.loads(text)
                            
                            # The JSON structure may vary - try common formats
                            # It might be a list, or an object with a 'stations' or 'features' key
                            if isinstance(data, list):
                                station_list = data
                            elif isinstance(data, dict):
                                # Try common keys
                                station_list = (data.get('stations') or data.get('features') or 
                                               data.get('data') or [])
                            else:
                                station_list = []
                            
                            logger.debug(f"Found {len(station_list)} stations in JSON")
                            
                            # Log sample station structure for debugging
                            if station_list and len(station_list) > 0:
                                sample = station_list[0]
                                if isinstance(sample, dict):
                                    logger.debug(f"Sample station fields: {list(sample.keys())[:20]}")
                                    logger.debug(f"Sample station data: {dict(list(sample.items())[:10])}")
                            
                            # Parse each station
                            for station_obj in station_list:
                                try:
                                    # Handle different JSON structures
                                    if isinstance(station_obj, dict):
                                        # Try various possible field names
                                        icao = (station_obj.get('icao') or station_obj.get('id') or 
                                               station_obj.get('stationId') or station_obj.get('site'))
                                        
                                        # Get lat/lon - might be in 'geometry' or 'coordinates' or direct fields
                                        lat = None
                                        lon = None
                                        
                                        if 'lat' in station_obj and 'lon' in station_obj:
                                            lat = float(station_obj.get('lat', 0))
                                            lon = float(station_obj.get('lon', 0))
                                        elif 'latitude' in station_obj and 'longitude' in station_obj:
                                            lat = float(station_obj.get('latitude', 0))
                                            lon = float(station_obj.get('longitude', 0))
                                        elif 'geometry' in station_obj:
                                            geom = station_obj['geometry']
                                            if isinstance(geom, dict) and 'coordinates' in geom:
                                                coords = geom['coordinates']
                                                if isinstance(coords, list) and len(coords) >= 2:
                                                    lon = float(coords[0])  # GeoJSON is lon, lat
                                                    lat = float(coords[1])
                                        elif 'coordinates' in station_obj:
                                            coords = station_obj['coordinates']
                                            if isinstance(coords, list) and len(coords) >= 2:
                                                lon = float(coords[0])
                                                lat = float(coords[1])
                                        
                                        # Don't set name - it will be replaced by airport name from CSV
                                        # This ensures all names come from the authoritative airports.csv source
                                        
                                        country = (station_obj.get('country') or station_obj.get('countryCode') or '')
                                        
                                        if icao and len(str(icao)) == 4:
                                            stations.append({
                                                "icao": str(icao).upper(),
                                                "lat": lat or 0.0,
                                                "lon": lon or 0.0,
                                                "name": "",  # Empty - will be replaced by airport name from CSV
                                                "country": str(country).strip() or "Unknown",
                                            })
                                except (ValueError, KeyError, TypeError) as e:
                                    logger.debug(f"Error parsing station object: {e}")
                                    continue
                            
                            logger.info(f"Downloaded {len(stations)} stations from cache file")
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON parse error: {e}")
                            logger.debug(f"JSON sample (first 500 chars): {text[:500]}")
                    else:
                        error_text = await response.text() if hasattr(response, 'text') else ""
                        logger.warning(f"Failed to download stations cache JSON: HTTP {response.status} - {error_text[:200]}, trying XML")
                        # Fallback to XML if JSON fails
                        url = f"{self.CACHE_URL}/stations.cache.xml.gz"
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as xml_response:
                            if xml_response.status == 200:
                                compressed_data = await xml_response.read()
                                decompressed_data = gzip.decompress(compressed_data)
                                text = decompressed_data.decode('utf-8')
                                
                                # Parse XML
                                import xml.etree.ElementTree as ET
                                try:
                                    root = ET.fromstring(text)
                                    
                                    # Try different possible element names
                                    station_elems = (root.findall('.//station') or root.findall('.//Station') or
                                                    root.findall('.//{*}station') or root.findall('.//{*}Station'))
                                    
                                    if not station_elems:
                                        # Try finding by iterating
                                        for elem in root.iter():
                                            if 'station' in elem.tag.lower():
                                                station_elems.append(elem)
                                    
                                    logger.debug(f"Found {len(station_elems)} station elements in XML")
                                    
                                    for station_elem in station_elems:
                                        try:
                                            icao = (station_elem.get('icao') or station_elem.get('id') or
                                                   station_elem.findtext('icao') or station_elem.findtext('id'))
                                            
                                            lat_str = (station_elem.get('lat') or station_elem.get('latitude') or
                                                      station_elem.findtext('lat') or station_elem.findtext('latitude'))
                                            lon_str = (station_elem.get('lon') or station_elem.get('longitude') or
                                                      station_elem.findtext('lon') or station_elem.findtext('longitude'))
                                            
                                            # Don't set name - it will be replaced by airport name from CSV
                                            # This ensures all names come from the authoritative airports.csv source
                                            
                                            country = (station_elem.get('country') or station_elem.findtext('country') or '')
                                            
                                            if icao and len(str(icao)) == 4:
                                                stations.append({
                                                    "icao": str(icao).upper(),
                                                    "lat": float(lat_str) if lat_str else 0.0,
                                                    "lon": float(lon_str) if lon_str else 0.0,
                                                    "name": "",  # Empty - will be replaced by airport name from CSV
                                                    "country": str(country).strip() or "Unknown",
                                                })
                                        except (ValueError, AttributeError) as e:
                                            logger.debug(f"Error parsing station element: {e}")
                                            continue
                                    
                                    logger.info(f"Downloaded {len(stations)} stations from cache XML file")
                                except ET.ParseError as e:
                                    logger.error(f"XML parse error: {e}")
                                    logger.debug(f"XML sample (first 500 chars): {text[:500]}")
                            else:
                                logger.error(f"Failed to download stations cache XML: HTTP {xml_response.status}")
        except Exception as e:
            logger.error(f"Error downloading stations: {e}", exc_info=True)
        
        # Enhance station names using local airport data cache (fast, no API calls)
        if stations:
            # Load cache if not already loaded (silent, no update)
            if not self.airport_data_cache:
                self.airport_data_cache = self.load_airport_data()
            
            logger.info(f"Enhancing {len(stations)} station names from local airport data cache...")
            stations = self.enhance_station_names_from_local_cache(stations)
            
            # Fallback: Use airportsdata library for airports not in local cache
            # NOTE: We do NOT call AviationWeather.gov API here - that's done by background task only
            stations_needing_enhancement = [
                s for s in stations 
                if not s.get("name") or s.get("name", "").startswith("Station ") or len(s.get("name", "")) < 5
            ]
            if stations_needing_enhancement and AIRPORTS_DATA_AVAILABLE:
                logger.info(f"Enhancing {len(stations_needing_enhancement)} remaining stations using airportsdata library...")
                stations = self.enhance_station_names_with_airports(stations)
            
            # Log if any stations still need names (will be updated by background task later)
            stations_still_needing = [
                s for s in stations 
                if not s.get("name") or s.get("name", "").startswith("Station ") or len(s.get("name", "")) < 5
            ]
            if stations_still_needing:
                logger.debug(f"{len(stations_still_needing)} stations still need names (will be updated by background task)")
        else:
            logger.warning("No stations to enhance - skipping airport name enhancement")
        
        # If we have existing stations.csv, merge it (it may have better lat/lon data)
        stations_csv = self.DATA_DIR / "stations.csv"
        if stations_csv.exists():
            import csv
            try:
                with open(stations_csv, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    csv_stations = {}
                    for row in reader:
                        icao = row.get("icao", "").strip().upper()
                        if icao and len(icao) == 4:
                            csv_stations[icao] = {
                                "icao": icao,
                                "lat": float(row.get("lat", 0)),
                                "lon": float(row.get("lon", 0)),
                                "name": row.get("name", "").strip(),
                                "country": row.get("country", "").strip(),
                            }
                    
                    # Merge: prioritize CSV data (has accurate lat/lon), add any downloaded stations not in CSV
                    merged = dict(csv_stations)  # Start with CSV stations
                    for station in stations:
                        icao = station["icao"]
                        if icao not in merged:
                            # Add downloaded station if not in CSV
                            merged[icao] = station
                        else:
                            # Keep CSV station name (from airports.csv) - don't replace with downloaded name
                            # Downloaded stations have empty names, so they will be replaced by airport names from CSV
                            
                            # Update coordinates if CSV has none
                            if merged[icao].get("lat") == 0.0 and merged[icao].get("lon") == 0.0:
                                if station.get("lat") != 0.0 or station.get("lon") != 0.0:
                                    merged[icao]["lat"] = station["lat"]
                                    merged[icao]["lon"] = station["lon"]
                            
                            # Update country if missing
                            if not merged[icao].get("country") or merged[icao].get("country") == "Unknown":
                                if station.get("country") and station.get("country") != "Unknown":
                                    merged[icao]["country"] = station["country"]
                    
                    stations = list(merged.values())
                    logger.info(f"Merged with CSV: {len(stations)} total stations ({len(csv_stations)} from CSV, {len(stations) - len(csv_stations)} from download)")
            except Exception as e:
                logger.warning(f"Error reading stations.csv: {e}, using downloaded stations only")
        
        return stations
    
    async def download_full_metar(self, icao_list: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Download full METAR list from AviationWeather.gov cache file.
        
        Args:
            icao_list: Optional list of ICAO codes (ignored when using cache - we get all METARs).
        
        Returns:
            Dictionary mapping ICAO codes to raw METAR strings
        """
        logger.info("Downloading full METAR list from AviationWeather.gov cache...")
        metars = {}
        
        try:
            # Use the METAR cache file which contains ALL current METARs worldwide
            # Updated once per minute according to API docs
            async with aiohttp.ClientSession() as session:
                # Try CSV format first (easier to parse)
                url = f"{self.CACHE_URL}/metars.cache.csv.gz"
                
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as response:
                    if response.status == 200:
                        # Decompress gzipped data
                        compressed_data = await response.read()
                        decompressed_data = gzip.decompress(compressed_data)
                        text = decompressed_data.decode('utf-8')
                        
                        # Parse CSV
                        import csv
                        from io import StringIO
                        reader = csv.DictReader(StringIO(text))
                        
                        # Log first few rows to understand structure
                        rows = list(reader)
                        if rows:
                            logger.info(f"CSV columns found: {list(rows[0].keys())}")
                            logger.debug(f"First row sample: {dict(list(rows[0].items())[:10])}")
                        else:
                            logger.warning("CSV file appears to be empty or has no data rows")
                            logger.debug(f"CSV text sample (first 500 chars): {text[:500]}")
                        
                        for row in rows:
                            # The actual column name from AviationWeather.gov is 'raw_text'
                            raw_metar = row.get('raw_text')
                            
                            if raw_metar and raw_metar.strip():
                                # Extract ICAO from METAR
                                parts = raw_metar.strip().split()
                                if len(parts) >= 2:
                                    icao = parts[1] if parts[0].upper() == "METAR" else parts[0]
                                    if len(icao) == 4 and icao.isalpha():
                                        icao_upper = icao.upper()
                                        metars[icao_upper] = raw_metar.strip()
                                elif len(parts) == 1 and len(parts[0]) == 4 and parts[0].isalpha():
                                    # METAR might not have "METAR" prefix, just ICAO
                                    icao_upper = parts[0].upper()
                                    metars[icao_upper] = raw_metar.strip()
                            else:
                                # Fallback: try to get ICAO from station_id column
                                icao = row.get('station_id')
                                if icao and len(str(icao)) == 4:
                                    logger.debug(f"Found ICAO {icao} but no raw_text in CSV row")
                        
                        if len(metars) == 0 and rows:
                            # Debug: check first few rows to see what's in raw_text
                            sample_raw_texts = [row.get('raw_text', '')[:50] for row in rows[:5]]
                            logger.warning(f"Parsed {len(rows)} CSV rows but found 0 METARs. Sample raw_text values: {sample_raw_texts}")
                        
                        logger.info(f"Downloaded {len(metars)} METAR reports from cache file")
                    else:
                        error_text = await response.text() if hasattr(response, 'text') else ""
                        logger.warning(f"Failed to download METAR cache CSV: HTTP {response.status} - {error_text[:200]}, trying XML")
                        # Fallback to XML if CSV fails
                        url = f"{self.CACHE_URL}/metars.cache.xml.gz"
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as xml_response:
                            if xml_response.status == 200:
                                compressed_data = await xml_response.read()
                                decompressed_data = gzip.decompress(compressed_data)
                                text = decompressed_data.decode('utf-8')
                                
                                # Parse XML
                                import xml.etree.ElementTree as ET
                                try:
                                    root = ET.fromstring(text)
                                    
                                    # Try different possible element names and structures
                                    metar_elems = (root.findall('.//METAR') or root.findall('.//metar') or 
                                                 root.findall('.//{*}METAR') or root.findall('.//{*}metar'))
                                    
                                    if not metar_elems:
                                        # Try finding by tag name directly
                                        for elem in root.iter():
                                            if elem.tag.upper().endswith('METAR') or 'METAR' in elem.tag.upper():
                                                metar_elems.append(elem)
                                    
                                    logger.debug(f"Found {len(metar_elems)} METAR elements in XML")
                                    
                                    for metar_elem in metar_elems:
                                        # Try various possible text fields
                                        # XML format may use different element names
                                        raw_metar = (metar_elem.findtext('rawText') or metar_elem.findtext('raw_text') or
                                                   metar_elem.findtext('rawOb') or metar_elem.findtext('raw') or 
                                                   metar_elem.findtext('text') or metar_elem.findtext('observation') or
                                                   metar_elem.text)
                                        
                                        if raw_metar and raw_metar.strip():
                                            parts = raw_metar.strip().split()
                                            if len(parts) >= 2:
                                                icao = parts[1] if parts[0].upper() == "METAR" else parts[0]
                                                if len(icao) == 4 and icao.isalpha():
                                                    icao_upper = icao.upper()
                                                    metars[icao_upper] = raw_metar.strip()
                                    
                                    logger.info(f"Downloaded {len(metars)} METAR reports from cache XML file")
                                except ET.ParseError as e:
                                    logger.error(f"XML parse error: {e}")
                                    logger.debug(f"XML sample (first 500 chars): {text[:500]}")
                            else:
                                logger.error(f"Failed to download METAR cache XML: HTTP {xml_response.status}")
        except Exception as e:
            logger.error(f"Error downloading METAR cache: {e}", exc_info=True)
        
        return metars
    
    async def download_full_taf(self, icao_list: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Download full TAF list from AviationWeather.gov cache file.
        
        Args:
            icao_list: Optional list of ICAO codes (ignored when using cache - we get all TAFs).
        
        Returns:
            Dictionary mapping ICAO codes to raw TAF strings
        """
        logger.info("Downloading full TAF list from AviationWeather.gov cache...")
        tafs = {}
        
        try:
            # Use the TAF cache file which contains ALL current TAFs worldwide
            # Updated every 10 minutes according to API docs
            async with aiohttp.ClientSession() as session:
                url = f"{self.CACHE_URL}/tafs.cache.xml.gz"
                
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as response:
                    if response.status == 200:
                        # Decompress gzipped data
                        compressed_data = await response.read()
                        decompressed_data = gzip.decompress(compressed_data)
                        text = decompressed_data.decode('utf-8')
                        
                        # Parse XML
                        import xml.etree.ElementTree as ET
                        try:
                            root = ET.fromstring(text)
                            
                            # Try different possible element names and structures
                            taf_elems = (root.findall('.//TAF') or root.findall('.//taf') or 
                                        root.findall('.//{*}TAF') or root.findall('.//{*}taf'))
                            
                            if not taf_elems:
                                # Try finding by tag name directly
                                for elem in root.iter():
                                    if elem.tag.upper().endswith('TAF') or 'TAF' in elem.tag.upper():
                                        taf_elems.append(elem)
                            
                            logger.debug(f"Found {len(taf_elems)} TAF elements in XML")
                            
                            # Log first element structure for debugging
                            if taf_elems:
                                first_elem = taf_elems[0]
                                logger.debug(f"First TAF element tag: {first_elem.tag}")
                                logger.debug(f"First TAF element attributes: {first_elem.attrib}")
                                logger.debug(f"First TAF element children: {[child.tag for child in first_elem]}")
                                # Try to find raw text in first element
                                sample_raw = (first_elem.findtext('rawText') or first_elem.findtext('rawTaf') or
                                            first_elem.findtext('raw') or first_elem.findtext('text') or
                                            first_elem.findtext('forecast') or first_elem.text)
                                if sample_raw:
                                    logger.debug(f"Sample raw TAF text (first 100 chars): {sample_raw[:100]}")
                            
                            for taf_elem in taf_elems:
                                # Try various possible text fields
                                raw_taf = (taf_elem.findtext('rawText') or taf_elem.findtext('rawTaf') or
                                         taf_elem.findtext('raw_text') or taf_elem.findtext('rawOb') or
                                         taf_elem.findtext('raw') or taf_elem.findtext('text') or
                                         taf_elem.findtext('forecast') or taf_elem.findtext('observation') or
                                         taf_elem.text)
                                
                                if raw_taf and raw_taf.strip():
                                    # Extract ICAO from TAF
                                    parts = raw_taf.strip().split()
                                    if len(parts) >= 2:
                                        icao = parts[1] if parts[0].upper() == "TAF" else parts[0]
                                        if len(icao) == 4 and icao.isalpha():
                                            icao_upper = icao.upper()
                                            tafs[icao_upper] = raw_taf.strip()
                                    elif len(parts) == 1 and len(parts[0]) == 4 and parts[0].isalpha():
                                        # TAF might not have "TAF" prefix, just ICAO
                                        icao_upper = parts[0].upper()
                                        tafs[icao_upper] = raw_taf.strip()
                                
                                # Fallback: try to get ICAO from attributes or child elements if we have raw text but couldn't extract ICAO
                                if (raw_taf and raw_taf.strip() and 
                                    not any(icao in tafs for icao in [parts[0].upper() if parts else '', 
                                                                      parts[1].upper() if len(parts) > 1 else ''])):
                                    icao = (taf_elem.get('icao') or taf_elem.get('station') or taf_elem.get('stationId') or
                                           taf_elem.findtext('icao') or taf_elem.findtext('station') or
                                           taf_elem.findtext('stationId') or taf_elem.findtext('site'))
                                    if icao and len(str(icao)) == 4:
                                        icao_upper = str(icao).upper()
                                        tafs[icao_upper] = raw_taf.strip()
                                        logger.debug(f"Used ICAO from XML attributes/elements: {icao_upper}")
                                
                                # If still no raw text, log for debugging
                                if not raw_taf or not raw_taf.strip():
                                    icao = (taf_elem.get('icao') or taf_elem.get('station') or
                                           taf_elem.findtext('icao') or taf_elem.findtext('station') or
                                           taf_elem.findtext('site'))
                                    if icao and len(str(icao)) == 4:
                                        logger.debug(f"Found ICAO {icao} in XML but no raw TAF text")
                            
                            if len(tafs) == 0 and taf_elems:
                                logger.warning(f"Parsed {len(taf_elems)} TAF XML elements but found 0 TAFs. Check XML structure.")
                            
                            logger.info(f"Downloaded {len(tafs)} TAF reports from cache file")
                        except ET.ParseError as e:
                            logger.error(f"XML parse error: {e}")
                            logger.debug(f"XML sample (first 500 chars): {text[:500]}")
                    else:
                        error_text = await response.text() if hasattr(response, 'text') else ""
                        logger.error(f"Failed to download TAF cache: HTTP {response.status} - {error_text[:200]}")
        except Exception as e:
            logger.error(f"Error downloading TAF cache: {e}", exc_info=True)
        
        return tafs
    
    def save_stations(self, stations: List[Dict]) -> None:
        """Save stations to file."""
        try:
            data = {
                "timestamp": time.time(),
                "count": len(stations),
                "stations": stations,
            }
            
            with open(self.STATIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved {len(stations)} stations to {self.STATIONS_FILE}")
        except Exception as e:
            logger.error(f"Error saving stations: {e}", exc_info=True)
    
    def load_stations(self) -> List[Dict]:
        """Load stations from file."""
        if not self.STATIONS_FILE.exists():
            return []
        
        try:
            with open(self.STATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                stations = data.get("stations", [])
                timestamp = data.get("timestamp", 0)
                age_hours = (time.time() - timestamp) / 3600
                logger.info(f"Loaded {len(stations)} stations from file (age: {age_hours:.1f} hours)")
                return stations
        except Exception as e:
            logger.error(f"Error loading stations: {e}", exc_info=True)
            return []
    
    def save_metar(self, metars: Dict[str, str], archive: bool = True) -> None:
        """Save METAR data to file, optionally archiving old file."""
        try:
            # Archive old file if it exists and archiving is enabled
            if archive and self.METAR_FILE.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_file = self.METAR_ARCHIVE_DIR / f"metar_{timestamp}.json"
                self.METAR_FILE.rename(archive_file)
                logger.debug(f"Archived old METAR to {archive_file}")
            
            # Save new data
            data = {
                "timestamp": time.time(),
                "count": len(metars),
                "metars": metars,
            }
            
            with open(self.METAR_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved {len(metars)} METAR reports to {self.METAR_FILE}")
        except Exception as e:
            logger.error(f"Error saving METAR: {e}", exc_info=True)
    
    def load_metar(self) -> Dict[str, str]:
        """Load METAR data from file."""
        if not self.METAR_FILE.exists():
            return {}
        
        try:
            with open(self.METAR_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                metars = data.get("metars", {})
                timestamp = data.get("timestamp", 0)
                age_hours = (time.time() - timestamp) / 3600
                logger.info(f"Loaded {len(metars)} METAR reports from file (age: {age_hours:.1f} hours)")
                return metars
        except Exception as e:
            logger.error(f"Error loading METAR: {e}", exc_info=True)
            return {}
    
    def save_taf(self, tafs: Dict[str, str], archive: bool = True) -> None:
        """Save TAF data to file, optionally archiving old file."""
        try:
            # Archive old file if it exists and archiving is enabled
            if archive and self.TAF_FILE.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_file = self.TAF_ARCHIVE_DIR / f"taf_{timestamp}.json"
                self.TAF_FILE.rename(archive_file)
                logger.debug(f"Archived old TAF to {archive_file}")
            
            # Save new data
            data = {
                "timestamp": time.time(),
                "count": len(tafs),
                "tafs": tafs,
            }
            
            with open(self.TAF_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved {len(tafs)} TAF reports to {self.TAF_FILE}")
        except Exception as e:
            logger.error(f"Error saving TAF: {e}", exc_info=True)
    
    def load_taf(self) -> Dict[str, str]:
        """Load TAF data from file."""
        if not self.TAF_FILE.exists():
            return {}
        
        try:
            with open(self.TAF_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                tafs = data.get("tafs", {})
                timestamp = data.get("timestamp", 0)
                age_hours = (time.time() - timestamp) / 3600
                logger.info(f"Loaded {len(tafs)} TAF reports from file (age: {age_hours:.1f} hours)")
                return tafs
        except Exception as e:
            logger.error(f"Error loading TAF: {e}", exc_info=True)
            return {}
    
    def should_refresh_stations(self) -> bool:
        """Check if stations should be refreshed."""
        if not self.STATIONS_FILE.exists():
            return True
        
        try:
            with open(self.STATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                timestamp = data.get("timestamp", 0)
                age_hours = (time.time() - timestamp) / 3600
                return age_hours > self.STATIONS_CACHE_HOURS
        except:
            return True
    
    def should_refresh_weather(self) -> bool:
        """Check if weather should be refreshed."""
        if not self.METAR_FILE.exists() or not self.TAF_FILE.exists():
            return True
        
        try:
            # Check METAR file age
            with open(self.METAR_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                timestamp = data.get("timestamp", 0)
                age_hours = (time.time() - timestamp) / 3600
                return age_hours > self.WEATHER_REFRESH_HOURS
        except:
            return True
    
    async def update_airport_data_from_aviationweather(self) -> Dict[str, Dict]:
        """
        Update local airport data cache from AviationWeather.gov API.
        This runs in the background weekly to keep airport data fresh.
        
        Returns:
            Dictionary mapping ICAO -> airport data
        """
        logger.debug("Updating airport data from AviationWeather.gov API (silent background task)...")
        
        # Get all known ICAO codes from stations
        all_icaos = set()
        stations_data = self.load_stations()
        for station in stations_data:
            icao = station.get("icao", "").upper()
            if icao and len(icao) == 4:
                all_icaos.add(icao)
        
        if not all_icaos:
            logger.warning("No ICAO codes found to update airport data")
            return {}
        
        airport_data = {}
        icao_list = sorted(list(all_icaos))
        batch_size = 50
        total_batches = (len(icao_list) + batch_size - 1) // batch_size
        
        logger.debug(f"Fetching airport data for {len(icao_list)} airports in {total_batches} batches (silent background task)...")
        
        try:
            async with aiohttp.ClientSession() as session:
                for i in range(0, len(icao_list), batch_size):
                    batch = icao_list[i:i + batch_size]
                    icao_string = ",".join(batch)
                    batch_num = (i // batch_size) + 1
                    
                    try:
                        url = f"{self.AIRPORT_API_URL}?ids={icao_string}&format=json"
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                            if response.status == 200:
                                data = await response.json()
                                airport_list = []
                                if isinstance(data, list):
                                    airport_list = data
                                elif isinstance(data, dict):
                                    airport_list = data.get('data', data.get('airports', []))
                                
                                for airport in airport_list:
                                    if not isinstance(airport, dict):
                                        continue
                                    airport_icao = (airport.get('icao') or airport.get('id') or 
                                                   airport.get('site') or '').upper()
                                    if airport_icao and len(airport_icao) == 4:
                                        airport_data[airport_icao] = airport
                                
                                logger.debug(f"Batch {batch_num}/{total_batches}: fetched {len(airport_list)} records")
                            elif response.status == 204:
                                logger.debug(f"Batch {batch_num}: No data available")
                    
                    except Exception as e:
                        logger.debug(f"Error fetching batch {batch_num}: {e}")
                        continue
                    
                    if i + batch_size < len(icao_list):
                        await asyncio.sleep(1)
            
            if airport_data:
                self.save_airport_data(airport_data)
                logger.debug(f"Updated airport data cache: {len(airport_data)} airports saved (silent background task)")
        
        except Exception as e:
            logger.error(f"Error updating airport data: {e}", exc_info=True)
        
        return airport_data
    
    def load_airport_data(self) -> Dict[str, Dict]:
        """Load airport data from local cache file."""
        if not self.AIRPORT_DATA_FILE.exists():
            return {}
        
        try:
            with open(self.AIRPORT_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                airports = data.get("airports", {})
                timestamp = data.get("timestamp", 0)
                age_hours = (time.time() - timestamp) / 3600
                logger.info(f"Loaded {len(airports)} airports from cache (age: {age_hours:.1f} hours)")
                return airports
        except Exception as e:
            logger.warning(f"Error loading airport data cache: {e}")
            return {}
    
    def save_airport_data(self, airport_data: Dict[str, Dict]) -> None:
        """Save airport data to local cache file."""
        try:
            data = {
                "timestamp": time.time(),
                "count": len(airport_data),
                "airports": airport_data,
            }
            with open(self.AIRPORT_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved {len(airport_data)} airports to {self.AIRPORT_DATA_FILE} (silent background task)")
        except Exception as e:
            logger.error(f"Error saving airport data: {e}", exc_info=True)
    
    def enhance_station_names_from_local_cache(self, stations: List[Dict]) -> List[Dict]:
        """
        Enhance station names using local airport data cache.
        This is fast and doesn't require API calls.
        """
        # Load airport data from local cache
        if not self.airport_data_cache:
            self.airport_data_cache = self.load_airport_data()
        
        if not self.airport_data_cache:
            logger.debug("No airport data in local cache")
            return stations
        
        enhanced_count = 0
        for station in stations:
            icao = station.get("icao", "").upper()
            if not icao or len(icao) != 4:
                continue
            
            airport = self.airport_data_cache.get(icao)
            if airport and isinstance(airport, dict):
                airport_name = (airport.get('name') or airport.get('siteName') or
                               airport.get('airportName') or airport.get('facilityName') or
                               airport.get('location') or '').strip()
                
                if airport_name:
                    station["name"] = airport_name
                    enhanced_count += 1
                    
                    if not station.get("country") or station.get("country") == "Unknown":
                        airport_country = (airport.get('country') or 
                                          airport.get('countryCode') or '').strip()
                        if airport_country:
                            station["country"] = airport_country
        
        if enhanced_count > 0:
            logger.info(f"Enhanced {enhanced_count} station names from local airport data cache")
        
        return stations
    
    async def enhance_station_names_from_aviationweather(self, stations: List[Dict]) -> List[Dict]:
        """
        Enhance station names using AviationWeather.gov airport API.
        
        Args:
            stations: List of station dictionaries
            
        Returns:
            Enhanced list of stations with better names
        """
        if not stations:
            return stations
        
        logger.info(f"Enhancing {len(stations)} station names from AviationWeather.gov airport data...")
        
        # Collect unique ICAO codes
        icao_list = [s.get("icao", "").upper() for s in stations if s.get("icao") and len(s.get("icao", "")) == 4]
        if not icao_list:
            return stations
        
        # Create mapping for quick lookup
        station_map = {s.get("icao", "").upper(): s for s in stations if s.get("icao")}
        
        # Fetch airport info in batches (API limit: 100 requests/minute, so batch by 50 to be safe)
        batch_size = 50
        enhanced_count = 0
        total_batches = (len(icao_list) + batch_size - 1) // batch_size
        
        logger.info(f"Processing {total_batches} batch(es) of up to {batch_size} airports each...")
        
        try:
            async with aiohttp.ClientSession() as session:
                for i in range(0, len(icao_list), batch_size):
                    batch = icao_list[i:i + batch_size]
                    icao_string = ",".join(batch)
                    batch_num = (i // batch_size) + 1
                    
                    logger.info(f"Fetching airport data for batch {batch_num}/{total_batches} ({len(batch)} airports): {icao_string[:50]}...")
                    
                    try:
                        # Fetch airport info for this batch
                        url = f"{self.AIRPORT_API_URL}?ids={icao_string}&format=json"
                        logger.debug(f"Requesting: {url}")
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                            if response.status == 200:
                                data = await response.json()
                                
                                # Handle different response formats
                                airport_list = []
                                if isinstance(data, list):
                                    airport_list = data
                                elif isinstance(data, dict):
                                    airport_list = data.get('data', data.get('airports', []))
                                
                                logger.info(f"Received {len(airport_list)} airport records for batch {batch_num}")
                                
                                # Log sample airport record structure for debugging
                                if airport_list and len(airport_list) > 0:
                                    sample = airport_list[0]
                                    if isinstance(sample, dict):
                                        logger.debug(f"Sample airport record fields: {list(sample.keys())}")
                                        logger.debug(f"Sample airport data: {dict(list(sample.items())[:5])}")
                                
                                # Update station names with airport data
                                batch_enhanced = 0
                                for airport in airport_list:
                                    if not isinstance(airport, dict):
                                        continue
                                    
                                    # Get ICAO from airport data - try multiple field names
                                    # AviationWeather.gov API uses 'icaoId' as the field name
                                    airport_icao = (airport.get('icaoId') or airport.get('icao') or 
                                                   airport.get('id') or airport.get('site') or 
                                                   airport.get('siteId') or airport.get('stationId') or '').upper()
                                    if not airport_icao:
                                        logger.warning(f"Skipping airport record with no ICAO. Available fields: {list(airport.keys())}")
                                        logger.debug(f"Full airport record: {dict(list(airport.items())[:10])}")
                                        continue
                                    
                                    logger.info(f"API returned airport with ICAO: {airport_icao}, station_map has {len(station_map)} stations")
                                    
                                    # Check if this airport ICAO matches a station
                                    if airport_icao not in station_map:
                                        # Try case-insensitive lookup
                                        found = False
                                        for key in station_map.keys():
                                            if key.upper() == airport_icao:
                                                airport_icao = key
                                                found = True
                                                break
                                        if not found:
                                            # This airport is not in our station list - log for debugging
                                            sample_stations = list(station_map.keys())[:5]
                                            logger.warning(f"Airport ICAO {airport_icao} from API not found in station map. Station map sample: {sample_stations}")
                                            continue
                                    
                                    logger.info(f"Found matching station for ICAO: {airport_icao}")
                                    
                                    # We found a matching station
                                    station = station_map[airport_icao]
                                    
                                    # Check if station already has a name (shouldn't happen, but be safe)
                                    if station.get("name", "").strip():
                                        logger.debug(f"Station {airport_icao} already has name '{station.get('name')}', skipping")
                                        continue
                                    
                                    station = station_map[airport_icao]
                                    
                                    # Get airport name - try multiple fields
                                    airport_name = (airport.get('name') or airport.get('siteName') or
                                                   airport.get('airportName') or airport.get('facilityName') or
                                                   airport.get('location') or airport.get('description') or '').strip()
                                    
                                    if airport_name:
                                        current_name = station.get("name", "").strip()
                                        # Always replace with airport name from AviationWeather.gov
                                        station["name"] = airport_name
                                        enhanced_count += 1
                                        batch_enhanced += 1
                                        logger.info(f"Enhanced {airport_icao}: '{current_name}' -> '{airport_name}' (from API)")
                                    else:
                                        logger.warning(f"Airport {airport_icao} has no name field. Available fields: {list(airport.keys())}")
                                        # Log the actual airport data for debugging
                                        logger.debug(f"Airport data for {airport_icao}: {dict(list(airport.items())[:10])}")
                                    
                                    # Update country if missing
                                    if not station.get("country") or station.get("country") == "Unknown":
                                        airport_country = (airport.get('country') or 
                                                          airport.get('countryCode') or '').strip()
                                        if airport_country:
                                            station["country"] = airport_country
                                    
                                    # Update coordinates if missing
                                    if (station.get("lat") == 0.0 and station.get("lon") == 0.0):
                                        airport_lat = airport.get('lat') or airport.get('latitude')
                                        airport_lon = airport.get('lon') or airport.get('longitude')
                                        if airport_lat is not None and airport_lon is not None:
                                            try:
                                                station["lat"] = float(airport_lat)
                                                station["lon"] = float(airport_lon)
                                            except (ValueError, TypeError):
                                                pass
                                    
                                
                                logger.info(f"Batch {batch_num} complete: enhanced {batch_enhanced} station names")
                                
                                # Small delay to respect rate limits
                                await asyncio.sleep(0.1)
                            
                            elif response.status == 204:
                                # No content - airport data not available for these ICAOs (common for weather stations that aren't airports)
                                logger.debug(f"No airport data available for batch {batch_num} ({len(batch)} ICAOs)")
                            elif response.status == 404:
                                # Airport not found - that's okay, skip
                                logger.debug(f"Airport info not found for batch {batch_num}: {icao_string[:50]}")
                            else:
                                error_text = await response.text() if hasattr(response, 'text') else ""
                                logger.warning(f"Failed to fetch airport info for batch {batch_num}: HTTP {response.status} - {error_text[:200]}")
                    
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout fetching airport info for batch: {icao_string[:50]}")
                    except Exception as e:
                        logger.warning(f"Error fetching airport info for batch: {e}")
                        continue
                    
                    # Rate limiting: wait between batches
                    if i + batch_size < len(icao_list):
                        await asyncio.sleep(1)  # 1 second between batches
            
            if enhanced_count > 0:
                logger.info(f"Enhanced {enhanced_count} station names from AviationWeather.gov airport data")
        except Exception as e:
            logger.warning(f"Error enhancing station names from AviationWeather.gov: {e}", exc_info=True)
        
        return stations
    
    async def download_airports_csv(self) -> bool:
        """
        Download airports.csv from GitHub if it doesn't exist locally.
        
        Returns:
            True if file was downloaded or already exists, False on error
        """
        if self.AIRPORTS_CSV_FILE.exists():
            logger.debug("airports.csv already exists, skipping download")
            return True
        
        logger.info("Downloading airports.csv from GitHub...")
        try:
            url = "https://raw.githubusercontent.com/mborsetti/airportsdata/main/airportsdata/airports.csv"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status == 200:
                        content = await response.read()
                        # Save to file
                        with open(self.AIRPORTS_CSV_FILE, 'wb') as f:
                            f.write(content)
                        logger.info(f"Downloaded airports.csv ({len(content)} bytes) to {self.AIRPORTS_CSV_FILE}")
                        return True
                    else:
                        logger.warning(f"Failed to download airports.csv: HTTP {response.status}")
                        return False
        except Exception as e:
            logger.warning(f"Error downloading airports.csv: {e}", exc_info=True)
            return False
    
    def load_airports_from_csv(self) -> Dict[str, Dict]:
        """
        Load airports from local airports.csv file in data folder.
        
        Returns:
            Dictionary mapping ICAO codes to airport data dictionaries
        """
        if not self.AIRPORTS_CSV_FILE.exists():
            return {}
        
        airports = {}
        try:
            import csv
            with open(self.AIRPORTS_CSV_FILE, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    icao = row.get('icao', '').strip().upper()
                    if icao and len(icao) == 4:
                        airports[icao] = {
                            'icao': icao,
                            'iata': row.get('iata', '').strip(),
                            'name': row.get('name', '').strip(),
                            'city': row.get('city', '').strip(),
                            'subd': row.get('subd', '').strip(),
                            'country': row.get('country', '').strip(),
                            'lat': row.get('lat', '').strip(),
                            'lon': row.get('lon', '').strip(),
                            'elevation': row.get('elevation', '').strip(),
                        }
            logger.info(f"Loaded {len(airports)} airports from local airports.csv file")
        except Exception as e:
            logger.warning(f"Error loading airports.csv: {e}", exc_info=True)
            return {}
        
        return airports
    
    async def enhance_station_names_with_airports(self, stations: List[Dict]) -> List[Dict]:
        """
        Enhance station names using airport database.
        Tries local airports.csv first, then falls back to airportsdata library.
        
        Args:
            stations: List of station dictionaries
            
        Returns:
            Enhanced list of stations with better names
        """
        enhanced_count = 0
        
        # First, try loading from local airports.csv file
        if self.airports_csv_cache is None:
            self.airports_csv_cache = self.load_airports_from_csv()
        
        # If we have local CSV data, use it
        if self.airports_csv_cache:
            logger.debug(f"Using airports.csv cache with {len(self.airports_csv_cache)} airports")
            for station in stations:
                icao = station.get("icao", "").upper()
                if not icao or len(icao) != 4:
                    continue
                
                airport = self.airports_csv_cache.get(icao)
                if airport and isinstance(airport, dict):
                    airport_name = airport.get('name', '').strip()
                    if airport_name:
                        current_name = station.get("name", "").strip()
                        # Always replace station name with airport name from CSV (matching by ICAO)
                        station["name"] = airport_name
                        enhanced_count += 1
                        if current_name != airport_name:
                            logger.debug(f"Replaced {icao}: '{current_name}' -> '{airport_name}' (from CSV)")
                    
                    # Update country if missing
                    if not station.get("country") or station.get("country") == "Unknown":
                        airport_country = airport.get('country', '').strip()
                        if airport_country:
                            station["country"] = airport_country
                    
                    # Update coordinates if missing
                    if (station.get("lat") == 0.0 and station.get("lon") == 0.0):
                        try:
                            lat_str = airport.get('lat', '').strip()
                            lon_str = airport.get('lon', '').strip()
                            if lat_str and lon_str:
                                station["lat"] = float(lat_str)
                                station["lon"] = float(lon_str)
                        except (ValueError, TypeError):
                            pass
                else:
                    logger.debug(f"Airport {icao} not found in airports.csv cache")
        
        # Try airportsdata library as fallback for stations not found in CSV
        # This helps cover airports that might not be in the CSV file
        if AIRPORTS_DATA_AVAILABLE:
            try:
                global airports_db
                if airports_db is None:
                    try:
                        airports_db = airportsdata.load('ICAO')
                        logger.info("Loaded airport database from airportsdata library")
                    except Exception as e:
                        logger.warning(f"Could not load airport database: {e}")
                        return stations
                
                for station in stations:
                    icao = station.get("icao", "").upper()
                    if not icao or len(icao) != 4:
                        continue
                    
                    # Skip if already enhanced from CSV (has a name)
                    if station.get("name", "").strip():
                        continue
                    
                    airport = None
                    # Try direct lookup if database is ICAO-indexed
                    if icao in airports_db:
                        airport = airports_db[icao]
                    elif isinstance(airports_db, dict):
                        # Search through all airports (for IATA-indexed or other structures)
                        for key, airport_data in airports_db.items():
                            if isinstance(airport_data, dict):
                                # Check if this airport matches our ICAO
                                airport_icao = airport_data.get('icao', '').upper()
                                if airport_icao == icao:
                                    airport = airport_data
                                    break
                                # Also check if key itself is the ICAO (case-insensitive)
                                if isinstance(key, str) and key.upper() == icao:
                                    airport = airport_data
                                    break
                    
                    if airport and isinstance(airport, dict):
                        airport_name = airport.get('name', '').strip()
                        if airport_name:
                            current_name = station.get("name", "").strip()
                            # Always replace with airport name from database
                            station["name"] = airport_name
                            enhanced_count += 1
                            if current_name != airport_name:
                                logger.debug(f"Replaced {icao}: '{current_name}' -> '{airport_name}' (from library)")
                        
                        # Update country if missing
                        if not station.get("country") or station.get("country") == "Unknown":
                            airport_country = airport.get('country', '').strip()
                            if airport_country:
                                station["country"] = airport_country
                        
                        # Update coordinates if missing
                        if (station.get("lat") == 0.0 and station.get("lon") == 0.0):
                            airport_lat = airport.get('lat')
                            airport_lon = airport.get('lon')
                            if airport_lat is not None and airport_lon is not None:
                                try:
                                    station["lat"] = float(airport_lat)
                                    station["lon"] = float(airport_lon)
                                except (ValueError, TypeError):
                                    pass
            except Exception as e:
                logger.warning(f"Error enhancing station names with airportsdata library: {e}", exc_info=True)
        
        if enhanced_count > 0:
            source = "local airports.csv" if self.airports_csv_cache else "airportsdata library"
            logger.info(f"Enhanced {enhanced_count} station names using {source}")
        elif not self.airports_csv_cache and not AIRPORTS_DATA_AVAILABLE:
            logger.debug("No airport data source available (no airports.csv and airportsdata library not installed)")
        
        # Final fallback: Check online API for stations that still have empty names
        # After all attempts, set "Not defined" for stations that still don't have names
        stations_needing_names = [
            s for s in stations 
            if not s.get("name") or s.get("name", "").strip() == ""
        ]
        
        # Set "Not defined" for any stations that still don't have names after all enhancement attempts
        for station in stations:
            if not station.get("name") or station.get("name", "").strip() == "":
                station["name"] = "Not defined"
        
        if stations_needing_names:
            logger.info(f"Found {len(stations_needing_names)} stations with empty names, checking AviationWeather.gov API (online fallback)...")
            logger.info(f"Sample stations needing names (first 10 ICAOs): {[s.get('icao', '') for s in stations_needing_names[:10]]}")
            try:
                # Count how many have empty names before enhancement
                before_empty = sum(1 for s in stations_needing_names if not s.get("name", "").strip())
                logger.info(f"Before API call: {before_empty} stations with empty names")
                
                enhanced = await self.enhance_station_names_from_aviationweather(stations_needing_names)
                
                # Count how many got names after enhancement
                # The enhance_station_names_from_aviationweather modifies stations in-place
                after_empty = sum(1 for s in stations_needing_names if not s.get("name", "").strip())
                online_enhanced = before_empty - after_empty
                logger.info(f"After API call: {after_empty} stations still with empty names, {online_enhanced} were enhanced")
                
                if online_enhanced > 0:
                    logger.info(f"Enhanced {online_enhanced} station names from AviationWeather.gov API (online fallback)")
                elif before_empty > 0:
                    logger.warning(f"API returned data but enhanced 0 names. This might indicate ICAO matching issues or missing name fields in API response.")
            except Exception as e:
                logger.warning(f"Error fetching airport names from AviationWeather.gov API: {e}", exc_info=True)
        
        return stations
    
    def cleanup_old_archives(self, days_to_keep: int = 7) -> None:
        """Clean up old archive files, keeping only the last N days."""
        cutoff_time = time.time() - (days_to_keep * 24 * 3600)
        
        for archive_dir in [self.METAR_ARCHIVE_DIR, self.TAF_ARCHIVE_DIR]:
            if not archive_dir.exists():
                continue
            
            deleted = 0
            for file in archive_dir.glob("*.json"):
                if file.stat().st_mtime < cutoff_time:
                    try:
                        file.unlink()
                        deleted += 1
                    except Exception as e:
                        logger.warning(f"Could not delete archive {file}: {e}")
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old archive files from {archive_dir}")
