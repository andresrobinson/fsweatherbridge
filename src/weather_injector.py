"""Weather injection interface."""

import ctypes
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from ctypes import byref, c_char_p, c_double, c_float, c_int, c_uint, c_ulong, c_void_p, POINTER
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.weather_smoother import WeatherState

logger = logging.getLogger(__name__)

# Try to import FSUIPC for weather injection
FSUIPC_AVAILABLE = False
FSUIPC = None
FSUIPCException = Exception
try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "fsuipc-master"))
    from fsuipc import FSUIPC, FSUIPCException
    FSUIPC_AVAILABLE = True
except (ImportError, OSError, ModuleNotFoundError):
    FSUIPC_AVAILABLE = False
    FSUIPC = None

# SimConnect constants
SIMCONNECT_OBJECT_ID_USER = 0
SIMCONNECT_OPEN_CONFIGINDEX_LOCAL = 0

# SimConnect weather observation structure
class SIMCONNECT_DATA_WEATHER_OBSERVATION(ctypes.Structure):
    _fields_ = [
        ("Metar", c_char_p),  # METAR string
    ]

# Try to load SimConnect.dll
SIMCONNECT_AVAILABLE = False
SimConnectDLL = None

# Common SimConnect.dll locations
simconnect_paths = [
    # FSX SDK location (various possible paths)
    r"C:\Program Files (x86)\Microsoft Games\Microsoft Flight Simulator X SDK\SDK\Core Utilities Kit\SimConnect SDK\lib\SimConnect.dll",
    r"C:\Program Files\Microsoft Games\Microsoft Flight Simulator X SDK\SDK\Core Utilities Kit\SimConnect SDK\lib\SimConnect.dll",
    # FSX installation (various possible paths)
    r"C:\Program Files (x86)\Microsoft Games\Microsoft Flight Simulator X\SimConnect.dll",
    r"C:\Program Files\Microsoft Games\Microsoft Flight Simulator X\SimConnect.dll",
    # Steam edition
    r"C:\Program Files (x86)\Steam\steamapps\common\FSX\SimConnect.dll",
    r"C:\Program Files\Steam\steamapps\common\FSX\SimConnect.dll",
    # Alternative locations
    r"C:\Windows\System32\SimConnect.dll",
    r"C:\Windows\SysWOW64\SimConnect.dll",
]

# First, try to find it in common locations
for path in simconnect_paths:
    if os.path.exists(path):
        try:
            SimConnectDLL = ctypes.WinDLL(path)
            SIMCONNECT_AVAILABLE = True
            logger.info(f"Found SimConnect.dll at: {path}")
            break
        except Exception as e:
            logger.debug(f"Failed to load SimConnect.dll from {path}: {e}")
            continue

# If not found, try loading by name (Windows will search PATH and registered DLLs)
if not SIMCONNECT_AVAILABLE:
    try:
        SimConnectDLL = ctypes.WinDLL("SimConnect.dll")
        SIMCONNECT_AVAILABLE = True
        logger.info("Loaded SimConnect.dll from system PATH or registered location")
    except Exception as e:
        logger.debug(f"Failed to load SimConnect.dll by name: {e}")

if not SIMCONNECT_AVAILABLE:
    logger.warning("SimConnect.dll not found. Weather injection via SimConnect will not be available.")
    logger.warning("SimConnect.dll is typically installed with FSX SDK or can be downloaded from Microsoft.")
    logger.warning("If FSX is installed, SimConnect.dll should be in the FSX installation directory or Windows system folders.")


class WeatherInjector(ABC):
    """Abstract weather injector."""
    
    @abstractmethod
    def inject_weather(self, weather: WeatherState, aircraft_lat: Optional[float] = None, aircraft_lon: Optional[float] = None, station_icao: Optional[str] = None) -> bool:
        """
        Inject weather into simulator.
        
        Args:
            weather: Weather state to inject
            aircraft_lat: Aircraft latitude (for station-based injection)
            aircraft_lon: Aircraft longitude (for station-based injection)
            station_icao: Optional station ICAO code for station-specific injection
        
        Returns:
            True if successful, False otherwise
        """
        pass


class DEVInjector(WeatherInjector):
    """Development injector that logs weather."""
    
    def __init__(self):
        self.last_injected: Dict = {}
    
    def inject_weather(self, weather: WeatherState, aircraft_lat: Optional[float] = None, aircraft_lon: Optional[float] = None, station_icao: Optional[str] = None) -> bool:
        """Log weather injection (DEV mode)."""
        self.last_injected = weather.to_dict()
        logger.info(f"[DEV] Weather injection: {self.last_injected}")
        return True
    
    def get_last_injected(self) -> Dict:
        """Get last injected weather (for testing)."""
        return self.last_injected


class FSUIPCWeatherInjector(WeatherInjector):
    """FSUIPC-based weather injector for FSX.
    
    Writes METAR strings to FSUIPC offset 0xB000, which FSUIPC then sends to SimConnect.
    This method is documented by Pete Dowson (FSUIPC author).
    
    IMPORTANT: Always uses station-based injection (never GLOB). FSX will blend weather
    from multiple stations automatically. GLOB should not be used as it overwrites station weather.
    
    References:
    - https://forum.simflight.com/topic/74632-setting-weather-through-fsuipc-in-fsx/
    - https://forum.simflight.com/topic/74901-writing-weather-as-a-metar-string-for-fsx/
    """
    
    def __init__(self, fsuipc_bridge, station_selection_config=None, station_db=None):
        """Initialize FSUIPC weather injector.
        
        Args:
            fsuipc_bridge: FSUIPCBridge instance (must have a connected FSUIPC connection)
            station_selection_config: StationSelectionConfig for finding nearest stations
            station_db: StationDatabase instance (pre-loaded with stations)
        """
        if not FSUIPC_AVAILABLE:
            raise RuntimeError("FSUIPC library not available. Cannot initialize FSUIPCWeatherInjector.")
        
        if not fsuipc_bridge:
            raise RuntimeError("FSUIPCBridge not provided. Cannot initialize FSUIPCWeatherInjector.")
        
        self.fsuipc_bridge = fsuipc_bridge
        self.station_selection_config = station_selection_config
        self.station_db = station_db  # Use pre-loaded station database
        logger.info("FSUIPCWeatherInjector initialized (using FSUIPC offset 0xB000 for station-based METAR injection)")
    
    def inject_station_metars(self, stations_with_metars: List[Tuple[str, object, float]], max_stations: int = 5) -> bool:
        """Inject METARs for multiple stations and let FSX blend them automatically.
        
        This is the preferred method - inject raw METARs for nearby stations and let FSX
        do the blending, which provides smooth transitions as the aircraft moves.
        
        Args:
            stations_with_metars: List of tuples (station_icao, parsed_metar, distance_nm)
            max_stations: Maximum number of stations to inject (closest ones)
        
        Returns:
            True if at least one station was injected successfully
        """
        if not self.fsuipc_bridge or not self.fsuipc_bridge.is_connected():
            logger.warning("FSUIPC not connected, cannot inject weather")
            return False
        
        if not self.fsuipc_bridge.connection:
            logger.warning("FSUIPC connection object not available")
            return False
        
        if not stations_with_metars:
            logger.warning("No stations provided for injection")
            return False
        
        try:
            # Ensure SimConnect is in Custom mode
            self._ensure_simconnect_custom_mode()
            
            # Sort by distance and take closest stations
            sorted_stations = sorted(stations_with_metars, key=lambda x: x[2])[:max_stations]
            
            # Validate stations for consistency - filter out stations with inconsistent weather
            validated_stations = self._validate_station_consistency(sorted_stations)
            
            success_count = 0
            for station_icao, parsed_metar, distance_nm in validated_stations:
                if not parsed_metar or not getattr(parsed_metar, 'valid', False):
                    logger.debug(f"Skipping {station_icao}: invalid or missing METAR")
                    continue
                
                # Build METAR string from parsed METAR (use raw data, not blended)
                metar_string = self._build_metar_from_parsed(parsed_metar, station_icao)
                
                if not metar_string:
                    logger.warning(f"Failed to build METAR string for {station_icao}")
                    continue
                
                # Convert to bytes with null terminator
                metar_bytes = metar_string.encode('utf-8') + b'\x00'
                
                logger.info(f"Injecting METAR for {station_icao} (distance: {distance_nm:.1f}nm): {metar_string}")
                
                # Write to FSUIPC offset 0xB000
                try:
                    self.fsuipc_bridge.connection.write([(0xB000, -256, metar_bytes)])
                    success_count += 1
                    # Small delay between stations to let FSUIPC/SimConnect process
                    time.sleep(0.1)
                except Exception as e:
                    logger.warning(f"Failed to write METAR for {station_icao}: {e}")
                    continue
            
            if success_count > 0:
                logger.info(f"Injected METARs for {success_count} station(s) - FSX will blend them automatically")
                # Final delay to let all writes process
                time.sleep(0.2)
                return True
            else:
                logger.warning("No stations were injected successfully")
                return False
                
        except Exception as e:
            logger.error(f"Error injecting station METARs: {e}", exc_info=True)
            return False
    
    def _build_metar_from_parsed(self, parsed_metar, station_icao: str) -> Optional[str]:
        """Build a METAR string from a parsed METAR object.
        
        Uses the raw METAR data directly, not blended weather.
        """
        from datetime import datetime
        
        parts = []
        
        # Station identifier
        parts.append(station_icao.upper())
        parts.append("METAR")
        
        # Date/time (format: DDHHMMZ) - use current UTC time
        now = datetime.utcnow()
        date_time = now.strftime("%d%H%MZ")
        parts.append(date_time)
        
        # Wind
        if parsed_metar.wind_dir_deg is not None and parsed_metar.wind_speed_kt is not None:
            wind_dir = int(parsed_metar.wind_dir_deg) % 360
            wind_speed = int(parsed_metar.wind_speed_kt)
            if wind_speed >= 10 and wind_dir == 0:
                wind_dir = 90
            if wind_speed == 0:
                parts.append("00000KT")
            else:
                parts.append(f"{wind_dir:03d}{wind_speed:02d}KT")
                if parsed_metar.wind_gust_kt is not None and parsed_metar.wind_gust_kt > parsed_metar.wind_speed_kt:
                    gust = int(parsed_metar.wind_gust_kt)
                    parts[-1] = f"{wind_dir:03d}{wind_speed:02d}G{gust:02d}KT"
        else:
            parts.append("00000KT")
        
        # Visibility - convert to ICAO-style meter steps
        if parsed_metar.visibility_nm is not None:
            vis_m = parsed_metar.visibility_nm * 1852
            if vis_m < 400:
                vis_m = 400
            if vis_m >= 10000:
                parts.append("9999")
            else:
                # Determine visibility value based on ICAO steps
                if vis_m >= 8000:
                    vis_value = 8000
                elif vis_m >= 5000:
                    vis_value = 5000
                elif vis_m >= 3000:
                    vis_value = 3000
                elif vis_m >= 1600:
                    vis_value = 1600
                elif vis_m >= 800:
                    vis_value = 800
                else:
                    vis_value = 400
                parts.append(f"{vis_value:04d}")
        else:
            parts.append("9999")
        
        # Weather phenomena
        if hasattr(parsed_metar, 'weather_tokens') and parsed_metar.weather_tokens:
            wx_codes = []
            for token in parsed_metar.weather_tokens[:2]:
                if "RA" in token.upper():
                    wx_codes.append("RA")
                elif "SN" in token.upper():
                    wx_codes.append("SN")
                elif "FG" in token.upper():
                    wx_codes.append("FG")
            if wx_codes:
                parts.extend(wx_codes)
        
        # Clouds
        if hasattr(parsed_metar, 'clouds') and parsed_metar.clouds:
            cloud_parts = []
            for cloud in parsed_metar.clouds[:3]:
                if hasattr(cloud, 'coverage') and hasattr(cloud, 'base_ft'):
                    coverage = cloud.coverage
                    base_ft = cloud.base_ft
                    base_100ft = max(5, int(base_ft / 100))
                    cov_map = {
                        'FEW': 'FEW', 'SCT': 'SCT', 'BKN': 'BKN', 'OVC': 'OVC', 'CLR': 'SKC', 'SKC': 'SKC'
                    }
                    cov_code = cov_map.get(coverage, 'SCT')
                    cloud_parts.append(f"{cov_code}{base_100ft:03d}")
            if cloud_parts:
                parts.extend(cloud_parts)
        else:
            parts.append("SKC")
        
        # Temperature and dewpoint
        if parsed_metar.temperature_c is not None:
            temp = int(parsed_metar.temperature_c)
            dewp = int(parsed_metar.dewpoint_c) if parsed_metar.dewpoint_c is not None else temp - 5
            parts.append(f"{temp:02d}/{dewp:02d}")
        
        # QNH (pressure)
        if parsed_metar.qnh_hpa is not None:
            qnh = parsed_metar.qnh_hpa
            if not (870 <= qnh <= 1080):
                logger.warning(f"QNH value {qnh} hPa is out of normal range for {station_icao}, using default 1013 hPa")
                qnh = 1013.25
            parts.append(f"Q{int(round(qnh))}")
        else:
            parts.append("Q1013")
        
        return " ".join(parts)
    
    def _validate_station_consistency(self, stations_with_metars: List[Tuple[str, object, float]]) -> List[Tuple[str, object, float]]:
        """Validate stations for weather consistency with nearby stations.
        
        Filters out stations that have significantly different weather compared to nearby stations.
        This helps avoid injecting bad/inconsistent METAR data.
        
        Args:
            stations_with_metars: List of tuples (station_icao, parsed_metar, distance_nm)
        
        Returns:
            Filtered list of stations with consistent weather
        """
        if len(stations_with_metars) <= 1:
            # Can't validate consistency with only one station
            return stations_with_metars
        
        validated = []
        rejected = []
        
        for i, (station_icao, parsed_metar, distance_nm) in enumerate(stations_with_metars):
            if not parsed_metar or not getattr(parsed_metar, 'valid', False):
                validated.append((station_icao, parsed_metar, distance_nm))
                continue
            
            # Compare with other nearby stations (within 20nm)
            nearby_stations = [
                (icao, metar, dist) for icao, metar, dist in stations_with_metars
                if icao != station_icao and dist <= 20.0 and metar and getattr(metar, 'valid', False)
            ]
            
            if not nearby_stations:
                # No nearby stations to compare - accept it
                validated.append((station_icao, parsed_metar, distance_nm))
                continue
            
            # Check visibility consistency
            station_vis = parsed_metar.visibility_nm
            if station_vis is not None:
                nearby_visibilities = [
                    metar.visibility_nm for _, metar, _ in nearby_stations
                    if metar.visibility_nm is not None
                ]
                
                if nearby_visibilities:
                    avg_nearby_vis = sum(nearby_visibilities) / len(nearby_visibilities)
                    vis_diff = abs(station_vis - avg_nearby_vis)
                    
                    # If visibility differs by more than 5nm and station has low vis while others have high vis (or vice versa)
                    if vis_diff > 5.0:
                        # Check if it's a significant mismatch (e.g., 0.2nm vs 10nm, or 10nm vs 0.2nm)
                        if (station_vis < 1.0 and avg_nearby_vis > 5.0) or (station_vis > 5.0 and avg_nearby_vis < 1.0):
                            logger.warning(f"Skipping {station_icao}: inconsistent visibility ({station_vis:.1f}nm vs nearby avg {avg_nearby_vis:.1f}nm, diff: {vis_diff:.1f}nm)")
                            rejected.append((station_icao, "visibility", vis_diff))
                            continue
            
            # Check QNH consistency (should be similar within ~50nm)
            station_qnh = parsed_metar.qnh_hpa
            if station_qnh is not None:
                nearby_qnhs = [
                    metar.qnh_hpa for _, metar, _ in nearby_stations
                    if metar.qnh_hpa is not None
                ]
                
                if nearby_qnhs:
                    avg_nearby_qnh = sum(nearby_qnhs) / len(nearby_qnhs)
                    qnh_diff = abs(station_qnh - avg_nearby_qnh)
                    
                    # QNH should be within ~10hPa of nearby stations (unless very far away)
                    if qnh_diff > 10.0 and distance_nm <= 20.0:
                        logger.warning(f"Skipping {station_icao}: inconsistent QNH ({station_qnh:.1f}hPa vs nearby avg {avg_nearby_qnh:.1f}hPa, diff: {qnh_diff:.1f}hPa)")
                        rejected.append((station_icao, "QNH", qnh_diff))
                        continue
            
            # Station passed validation
            validated.append((station_icao, parsed_metar, distance_nm))
        
        if rejected:
            logger.info(f"Filtered out {len(rejected)} inconsistent station(s): {[r[0] for r in rejected]}")
        
        return validated
    
    def inject_weather(self, weather: WeatherState, aircraft_lat: Optional[float] = None, aircraft_lon: Optional[float] = None, station_icao: Optional[str] = None) -> bool:
        """Inject weather via FSUIPC by writing METAR string to offset 0xB000.
        
        According to Pete Dowson (FSUIPC author):
        - Write METAR string to offset 0xB000 ONLY (no C800 commands needed)
        - Include null terminator (strlen+1)
        - FSUIPC sends the METAR to SimConnect, which applies it to FSX
        - ALWAYS use station-based injection (never GLOB)
        - FSX will automatically blend weather from multiple stations
        
        Format: "ICAO METAR DDHHMMZ dddssKT vis clouds temp/dew Q####"
        Example: "SBGR METAR 260608Z 27015KT 7SM BKN055 30/17 Q1019"
        
        References:
        - https://forum.simflight.com/topic/74632-setting-weather-through-fsuipc-in-fsx/
        - https://forum.simflight.com/topic/74901-writing-weather-as-a-metar-string-for-fsx/
        """
        if not self.fsuipc_bridge or not self.fsuipc_bridge.is_connected():
            logger.warning("FSUIPC not connected, cannot inject weather")
            return False
        
        if not self.fsuipc_bridge.connection:
            logger.warning("FSUIPC connection object not available")
            return False
        
        try:
            # CRITICAL: Since FSUIPC sends METAR to SimConnect, we should ensure SimConnect
            # is in Custom mode. Try to set it if SimConnect is available.
            self._ensure_simconnect_custom_mode()
            
            # ALWAYS use station-based injection (never GLOB)
            # GLOB overwrites station weather and prevents FSX from blending
            injection_icao = None
            
            if station_icao:
                # Use provided station ICAO
                injection_icao = station_icao.upper()
                logger.info(f"Using provided station ICAO for FSUIPC injection: {injection_icao}")
            elif aircraft_lat is not None and aircraft_lon is not None:
                # Find nearest station based on config settings
                if not self.station_db:
                    logger.error("Station database not provided to FSUIPCWeatherInjector - cannot find stations")
                    return False
                
                try:
                    # Use config settings for station selection
                    radius_nm = 50.0  # Default
                    if self.station_selection_config:
                        radius_nm = self.station_selection_config.radius_nm
                    
                    # Validate aircraft position
                    if abs(aircraft_lat) > 90 or abs(aircraft_lon) > 180:
                        logger.error(f"Invalid aircraft position: lat={aircraft_lat:.6f}, lon={aircraft_lon:.6f}")
                        return False
                    
                    logger.debug(f"Searching for stations near lat={aircraft_lat:.6f}, lon={aircraft_lon:.6f}, radius={radius_nm:.1f}nm")
                    logger.debug(f"Station database has {len(self.station_db.stations)} stations loaded")
                    
                    nearest = self.station_db.find_nearest_stations(
                        aircraft_lat, 
                        aircraft_lon, 
                        radius_nm=radius_nm,
                        max_results=1,
                        fallback_to_global=False  # Never fall back to global
                    )
                    
                    if nearest:
                        injection_icao = nearest[0][0].icao
                        distance = nearest[0][1]
                        logger.info(f"Found nearest station for FSUIPC injection: {injection_icao} (distance: {distance:.1f}nm, radius: {radius_nm:.1f}nm)")
                    else:
                        logger.warning(f"No station found within {radius_nm:.1f}nm of aircraft position (lat={aircraft_lat:.6f}, lon={aircraft_lon:.6f})")
                        logger.warning(f"Station database has {len(self.station_db.stations)} stations - may need to increase radius or check position")
                        logger.warning("Cannot inject weather without a station - GLOB is not used")
                        return False
                except Exception as e:
                    logger.error(f"Could not find nearest station: {e}", exc_info=True)
                    return False
            else:
                logger.warning("No aircraft position or station ICAO provided - cannot inject weather (station-based only)")
                return False
            
            # Build METAR string with station ICAO (never GLOB)
            metar = self._build_metar_string(weather, aircraft_lat, aircraft_lon, station_icao=injection_icao)
            
            if not metar:
                logger.warning("Failed to build METAR string for FSUIPC")
                return False
            
            # Convert to bytes with null terminator
            metar_bytes = metar.encode('utf-8') + b'\x00'
            
            logger.info(f"Writing station METAR to FSUIPC 0xB000: {metar}")
            logger.info(f"METAR bytes: {len(metar_bytes)} bytes (string: {len(metar)} chars)")
            
            # Write to FSUIPC offset 0xB000 ONLY (no C800 commands needed per Pete Dowson)
            # Negative length = null-terminated string (max length is absolute value)
            # Using -256 to allow up to 255 characters (typical METAR is ~80 chars)
            self.fsuipc_bridge.connection.write([(0xB000, -256, metar_bytes)])
            
            logger.info(f"FSUIPC write completed for station {injection_icao}")
            
            # Small delay to let FSUIPC/SimConnect process the write
            time.sleep(0.2)
            
            return True
            
        except FSUIPCException as e:
            logger.error(f"FSUIPC error injecting weather: {e}")
            return False
        except Exception as e:
            logger.error(f"Error injecting weather via FSUIPC: {e}")
            return False
    
    def _ensure_simconnect_custom_mode(self) -> None:
        """Try to set SimConnect to Custom mode if available.
        
        Since FSUIPC sends METAR to SimConnect, SimConnect should be in Custom mode.
        This is optional - if SimConnect isn't available, we continue anyway.
        """
        if not SIMCONNECT_AVAILABLE:
            return
        
        try:
            # Try to open SimConnect just for mode setting
            hSimConnect = c_void_p()
            result = SimConnectDLL.SimConnect_Open(
                byref(hSimConnect),
                b"FSXWeatherBridge",
                None,
                0,
                None,
                SIMCONNECT_OPEN_CONFIGINDEX_LOCAL
            )
            
            if result == 0:
                try:
                    # Set Custom mode
                    SimConnectDLL.SimConnect_WeatherSetModeCustom(hSimConnect)
                    # Pump dispatch a few times
                    for _ in range(5):
                        SimConnectDLL.SimConnect_CallDispatch(hSimConnect, None, None)
                    logger.debug("Set SimConnect to Custom mode for FSUIPC weather injection")
                finally:
                    # Close the temporary connection
                    SimConnectDLL.SimConnect_Close(hSimConnect)
        except Exception as e:
            logger.debug(f"Could not set SimConnect Custom mode (non-critical): {e}")
    
    def _build_metar_string(self, weather: WeatherState, lat: Optional[float] = None, lon: Optional[float] = None, station_icao: Optional[str] = None) -> Optional[str]:
        """Build a METAR string from weather state (same format as SimConnect).
        
        This is the same logic as SimConnectInjector._build_metar_string().
        FSUIPC sends the METAR string to SimConnect, so the format must match.
        """
        from datetime import datetime
        
        parts = []
        
        # Station identifier: ALWAYS use station ICAO (never GLOB)
        # GLOB overwrites station weather and prevents FSX from blending
        if station_icao:
            parts.append(station_icao.upper())
            parts.append("METAR")
        else:
            # This should never happen in FSUIPCWeatherInjector, but handle gracefully
            logger.warning("No station ICAO provided - using GLOB (not recommended)")
            parts.append("GLOB")
        
        # Date/time (format: DDHHMMZ) - use current UTC time
        now = datetime.utcnow()
        date_time = now.strftime("%d%H%MZ")
        parts.append(date_time)
        
        # Wind. Avoid 000ddKT when speed>=10 (calm direction at high speed edge case)
        if weather.wind_dir_deg is not None and weather.wind_speed_kt is not None:
            wind_dir = int(weather.wind_dir_deg) % 360
            wind_speed = int(weather.wind_speed_kt)
            if wind_speed >= 10 and wind_dir == 0:
                wind_dir = 90
            if wind_speed == 0:
                parts.append("00000KT")
            else:
                parts.append(f"{wind_dir:03d}{wind_speed:02d}KT")
                if weather.wind_gust_kt is not None and weather.wind_gust_kt > weather.wind_speed_kt:
                    gust = int(weather.wind_gust_kt)
                    parts[-1] = f"{wind_dir:03d}{wind_speed:02d}G{gust:02d}KT"
        else:
            parts.append("00000KT")
        
        # Visibility - use ICAO-style meter steps
        if weather.visibility_nm is not None:
            vis_m = int(weather.visibility_nm * 1852)
            if vis_m < 400:
                vis_m = 400
            if vis_m >= 10000:
                parts.append("9999")
            else:
                if vis_m >= 8000:
                    vis_value = 8000
                elif vis_m >= 5000:
                    vis_value = 5000
                elif vis_m >= 3000:
                    vis_value = 3000
                elif vis_m >= 1600:
                    vis_value = 1600
                elif vis_m >= 800:
                    vis_value = 800
                else:
                    vis_value = 400
                parts.append(f"{vis_value:04d}")
        else:
            parts.append("9999")
        
        # Weather phenomena
        if weather.weather_tokens:
            wx_codes = []
            for token in weather.weather_tokens:
                if "RA" in token.upper():
                    wx_codes.append("RA")
                elif "SN" in token.upper():
                    wx_codes.append("SN")
                elif "FG" in token.upper():
                    wx_codes.append("FG")
            if wx_codes:
                parts.append("".join(wx_codes[:2]))
        
        # Clouds (OVC000/BKN000 often invalid in FSX; use minimum 005 = 500 ft)
        if weather.clouds:
            cloud_parts = []
            for cloud in weather.clouds[:3]:
                if isinstance(cloud, dict):
                    coverage = cloud.get('coverage', 'SCT')
                    base_ft = cloud.get('base_ft', 3000)
                    base_100ft = max(5, int(base_ft / 100))
                    cov_map = {
                        'FEW': 'FEW', 'SCT': 'SCT', 'BKN': 'BKN', 'OVC': 'OVC', 'CLR': 'SKC'
                    }
                    cov_code = cov_map.get(coverage, 'SCT')
                    cloud_parts.append(f"{cov_code}{base_100ft:03d}")
            if cloud_parts:
                parts.extend(cloud_parts)
        else:
            parts.append("SKC")
        
        # Temperature and dewpoint
        if weather.temperature_c is not None:
            temp = int(weather.temperature_c)
            dewp = int(weather.dewpoint_c) if weather.dewpoint_c is not None else temp - 5
            parts.append(f"{temp:02d}/{dewp:02d}")
        
        # QNH (pressure)
        if weather.qnh_hpa is not None:
            qnh = weather.qnh_hpa
            if not (870 <= qnh <= 1080):
                logger.warning(f"QNH value {qnh} hPa is out of normal range, using default 1013 hPa")
                qnh = 1013.25
            parts.append(f"Q{int(round(qnh))}")
        else:
            parts.append("Q1013")
        
        return " ".join(parts)
    
    def inject_raw_metar(self, metar: str) -> bool:
        """Inject a raw METAR string directly via FSUIPC offset 0xB000."""
        if not self.fsuipc_bridge or not self.fsuipc_bridge.is_connected():
            return False
        if not self.fsuipc_bridge.connection:
            return False
        metar = (metar or "").strip()
        if not metar:
            return False
        try:
            metar_bytes = metar.encode('utf-8') + b'\x00'
            self.fsuipc_bridge.connection.write([(0xB000, -256, metar_bytes)])
            logger.info(f"FSUIPC raw METAR injection: {metar}")
            return True
        except Exception as e:
            logger.error(f"Error injecting raw METAR via FSUIPC: {e}")
            return False


class SimConnectInjector(WeatherInjector):
    """SimConnect-based injector for FSX."""
    
    def __init__(self):
        if not SIMCONNECT_AVAILABLE:
            raise RuntimeError("SimConnect.dll not available. Cannot initialize SimConnectInjector.")
        
        self.hSimConnect = c_void_p()
        self.connected = False
        self._setup_simconnect_functions()
        self._connect()
        # Store last mode set time to periodically re-enforce
        self.last_mode_set_time = 0
    
    def _setup_simconnect_functions(self):
        """Setup SimConnect function signatures."""
        try:
            # SimConnect_Open
            SimConnectDLL.SimConnect_Open.argtypes = [POINTER(c_void_p), c_char_p, c_void_p, c_uint, c_void_p, c_uint]
            SimConnectDLL.SimConnect_Open.restype = c_int
            
            # SimConnect_Close
            SimConnectDLL.SimConnect_Close.argtypes = [c_void_p]
            SimConnectDLL.SimConnect_Close.restype = c_int
            
            # SimConnect_WeatherSetObservation
            # Signature: SimConnect_WeatherSetObservation(HANDLE hSimConnect, DWORD Seconds, const char* szMETAR)
            # Parameters: hSimConnect, Seconds (time until observation), METAR string
            SimConnectDLL.SimConnect_WeatherSetObservation.argtypes = [
                c_void_p,
                c_uint,  # Seconds until observation takes effect
                c_char_p  # METAR string (must start with "GLOB" for global weather)
            ]
            SimConnectDLL.SimConnect_WeatherSetObservation.restype = c_int
            
            # SimConnect_WeatherSetModeServer
            SimConnectDLL.SimConnect_WeatherSetModeServer.argtypes = [
                c_void_p,
                c_uint,
                c_uint
            ]
            SimConnectDLL.SimConnect_WeatherSetModeServer.restype = c_int
            
            # SimConnect_WeatherSetModeCustom
            SimConnectDLL.SimConnect_WeatherSetModeCustom.argtypes = [
                c_void_p
            ]
            SimConnectDLL.SimConnect_WeatherSetModeCustom.restype = c_int
            
            # SimConnect_WeatherSetModeGlobal
            SimConnectDLL.SimConnect_WeatherSetModeGlobal.argtypes = [
                c_void_p
            ]
            SimConnectDLL.SimConnect_WeatherSetModeGlobal.restype = c_int
            
            # SimConnect_WeatherSetModeTheme
            SimConnectDLL.SimConnect_WeatherSetModeTheme.argtypes = [
                c_void_p,
                c_char_p
            ]
            SimConnectDLL.SimConnect_WeatherSetModeTheme.restype = c_int
            
            # SimConnect_CallDispatch
            SimConnectDLL.SimConnect_CallDispatch.argtypes = [c_void_p, c_void_p, c_void_p]
            SimConnectDLL.SimConnect_CallDispatch.restype = c_int
            
            logger.info("SimConnect function signatures configured")
        except Exception as e:
            logger.error(f"Failed to setup SimConnect functions: {e}")
            raise
    
    def _connect(self) -> bool:
        """Connect to SimConnect."""
        try:
            result = SimConnectDLL.SimConnect_Open(
                byref(self.hSimConnect),
                b"FSXWeatherBridge",
                None,
                0,
                None,
                SIMCONNECT_OPEN_CONFIGINDEX_LOCAL
            )
            
            if result == 0:  # SUCCESS
                self.connected = True
                logger.info("Connected to SimConnect")
                
                # CRITICAL: Set Custom mode ONCE after connect (and again on reconnect).
                # FSX must be in Custom mode before WeatherSetObservation takes effect.
                # Skipping WeatherSetModeCustom is a common reason for "returns success, no visible change".
                try:
                    result_custom = SimConnectDLL.SimConnect_WeatherSetModeCustom(self.hSimConnect)
                    if result_custom == 0:
                        logger.info("Set SimConnect weather mode to custom (WeatherSetModeCustom)")
                    else:
                        logger.warning(f"WeatherSetModeCustom returned error code: {result_custom}")
                except Exception as e:
                    logger.warning(f"Failed to set weather mode via WeatherSetModeCustom: {e}")
                
                # Pump SimConnect dispatch so the mode change is processed.
                # Ideally run a continuous dispatch loop (SimConnect_GetNextDispatch) in a background
                # thread; without it, commands may not reach FSX even if the API returns 0.
                self._pump_dispatch(20)
                time.sleep(0.1)
                
                self.last_mode_set_time = time.time()
                return True
            else:
                logger.error(f"Failed to connect to SimConnect. Error code: {result}")
                self.connected = False
                return False
        except Exception as e:
            logger.error(f"Exception connecting to SimConnect: {e}")
            self.connected = False
            return False
    
    def _pump_dispatch(self, n: int = 50) -> None:
        """Run SimConnect_CallDispatch n times to process pending messages.
        
        SimConnect requires pumping (CallDispatch or GetNextDispatch in a loop) for
        commands to be flushed and applied. Without it, weather and mode changes may
        not reach FSX even when the API returns 0.
        """
        try:
            for _ in range(n):
                SimConnectDLL.SimConnect_CallDispatch(self.hSimConnect, None, None)
        except Exception as e:
            logger.debug(f"Error in dispatch pump: {e}")
    
    def _ensure_custom_mode(self) -> None:
        """Re-enforce custom weather mode periodically (FSX may switch back to Real-World)."""
        current_time = time.time()
        if current_time - self.last_mode_set_time > 5.0:
            try:
                result_mode = SimConnectDLL.SimConnect_WeatherSetModeCustom(self.hSimConnect)
                if result_mode == 0:
                    self._pump_dispatch(5)
                    self.last_mode_set_time = current_time
                    logger.debug("Re-enforced custom weather mode")
            except Exception as e:
                logger.debug(f"Could not re-enforce custom mode: {e}")
    
    def inject_weather(self, weather: WeatherState, aircraft_lat: Optional[float] = None, aircraft_lon: Optional[float] = None, station_icao: Optional[str] = None) -> bool:
        """Inject weather via SimConnect using METAR string.
        
        Args:
            weather: Weather state to inject
            aircraft_lat: Aircraft latitude (for finding nearest station)
            aircraft_lon: Aircraft longitude (for finding nearest station)
            station_icao: Optional station ICAO code. If provided, uses station-specific injection.
                          If None and lat/lon provided, tries to find nearest station.
                          If None and no lat/lon, uses global injection.
        """
        if not self.connected:
            if not self._connect():
                return False
        
        try:
            # Ensure custom weather mode is set before injection
            self._ensure_custom_mode()
            
            # Determine injection method: station-specific or global
            # Some FSX setups don't accept GLOB, so try station-specific first if we have position
            use_station = False
            injection_icao = None
            
            if station_icao:
                # Use provided station ICAO
                use_station = True
                injection_icao = station_icao.upper()
                logger.info(f"Using provided station ICAO: {injection_icao}")
            elif aircraft_lat is not None and aircraft_lon is not None:
                # Try to find nearest station for station-specific injection
                # This is more reliable than GLOB in some FSX setups
                try:
                    from src.stations import StationDatabase
                    station_db = StationDatabase()
                    nearest = station_db.find_nearest_stations(aircraft_lat, aircraft_lon, radius_nm=50.0, max_results=1)
                    if nearest:
                        injection_icao = nearest[0][0].icao
                        use_station = True
                        logger.info(f"Using nearest station for injection: {injection_icao} (distance: {nearest[0][1]:.1f}nm)")
                    else:
                        logger.info("No nearby station found, using global injection")
                except Exception as e:
                    logger.debug(f"Could not find nearest station: {e}, using global injection")
            
            # Build METAR string from weather state
            metar = self._build_metar_string(weather, aircraft_lat, aircraft_lon, station_icao=injection_icao if use_station else None)
            
            if not metar:
                logger.warning("Failed to build METAR string")
                return False
            
            # Convert METAR to bytes (ensure null-terminated)
            metar_bytes = metar.encode('utf-8') + b'\x00'
            
            # Set Custom mode before observation (required; also done once at connect/reconnect).
            try:
                SimConnectDLL.SimConnect_WeatherSetModeCustom(self.hSimConnect)
                self._pump_dispatch(10)
            except Exception as e:
                logger.warning(f"Error setting Custom mode before injection: {e}")
            
            # SimConnect_WeatherSetObservation(hSimConnect, 0, "<METAR>")
            logger.info(f"Calling SimConnect_WeatherSetObservation with METAR: {metar}")
            result = SimConnectDLL.SimConnect_WeatherSetObservation(
                self.hSimConnect,
                0,  # Seconds=0 for immediate
                metar_bytes
            )
            logger.info(f"SimConnect_WeatherSetObservation returned: {result} (0=success, non-zero=error)")
            
            # Pump dispatch so the observation is processed. SimConnect needs this;
            # without a dispatch loop, observations may not be applied.
            self._pump_dispatch(50)
            
            if result == 0:
                logger.info(f"Weather injection succeeded. METAR: {metar}, method={'station' if use_station else 'global'}")
                try:
                    SimConnectDLL.SimConnect_WeatherSetModeCustom(self.hSimConnect)
                    self._pump_dispatch(5)
                except Exception:
                    pass
                return True
            else:
                logger.error(f"SimConnect_WeatherSetObservation failed. Error code: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error injecting weather via SimConnect: {e}")
            # Try to reconnect on error
            self.connected = False
            return False
    
    def inject_raw_metar(self, metar: str) -> bool:
        """Inject a raw METAR string directly. Use for manual/testing (e.g. GLOB 171844Z 09050KT 9999 SKC 15/10 Q1013 or SBGR METAR 171844Z 09050KT 1600 FG OVC005 15/10 Q1013)."""
        if not self.connected and not self._connect():
            return False
        metar = (metar or "").strip()
        if not metar:
            return False
        try:
            SimConnectDLL.SimConnect_WeatherSetModeCustom(self.hSimConnect)
            self._pump_dispatch(10)
            metar_bytes = metar.encode('utf-8') + b'\x00'
            result = SimConnectDLL.SimConnect_WeatherSetObservation(self.hSimConnect, 0, metar_bytes)
            self._pump_dispatch(50)
            if result == 0:
                logger.info(f"Raw METAR injection succeeded: {metar}")
                return True
            logger.error(f"SimConnect_WeatherSetObservation failed for raw METAR. Error: {result}")
            return False
        except Exception as e:
            logger.error(f"Error injecting raw METAR: {e}")
            self.connected = False
            return False
    
    def _build_metar_string(self, weather: WeatherState, lat: Optional[float] = None, lon: Optional[float] = None, station_icao: Optional[str] = None) -> Optional[str]:
        """Build a METAR string from weather state for SimConnect.
        
        Format for global weather: GLOB DDHHMMZ dddssKT vis clouds temp/dew pressure
        Example: GLOB 030405Z 27007KT 9999 SKC 17/13 Q1013
        
        Format for station weather: ICAO METAR DDHHMMZ dddssKT vis clouds temp/dew pressure
        Example: SBGR METAR 030405Z 13008KT 9999 SCT030 25/18 Q1013
        
        Note: For GLOB (global), do NOT include "METAR" keyword.
        For station-specific weather, MUST include "METAR" keyword after ICAO.
        
        Args:
            weather: Weather state
            lat: Latitude (unused, kept for compatibility)
            lon: Longitude (unused, kept for compatibility)
            station_icao: Station ICAO code. If provided, uses station format. If None, uses global format.
        """
        from datetime import datetime
        
        # Build METAR components - SimConnect format
        parts = []
        
        # Station identifier: use ICAO METAR for station, or GLOB for global.
        # Some FSX builds behave better with station injection than GLOB.
        if station_icao:
            parts.append(station_icao.upper())
            parts.append("METAR")
        else:
            parts.append("GLOB")
        
        # Date/time (format: DDHHMMZ) - use current UTC time
        now = datetime.utcnow()
        date_time = now.strftime("%d%H%MZ")
        parts.append(date_time)
        
        # Wind. Avoid 000ddKT when speed>=10 (calm direction at high speed edge case);
        # use 090ddKT instead (e.g. 09050KT).
        if weather.wind_dir_deg is not None and weather.wind_speed_kt is not None:
            wind_dir = int(weather.wind_dir_deg) % 360
            wind_speed = int(weather.wind_speed_kt)
            if wind_speed >= 10 and wind_dir == 0:
                wind_dir = 90
            if wind_speed == 0:
                parts.append("00000KT")
            else:
                parts.append(f"{wind_dir:03d}{wind_speed:02d}KT")
                if weather.wind_gust_kt is not None and weather.wind_gust_kt > weather.wind_speed_kt:
                    gust = int(weather.wind_gust_kt)
                    parts[-1] = f"{wind_dir:03d}{wind_speed:02d}G{gust:02d}KT"
        else:
            parts.append("00000KT")
        
        # Visibility - SimConnect format: use ICAO-style meter steps
        # Best practice: convert to meters and use ICAO steps (8000, 5000, 3000, 1600, 800, 400)
        # If visibility >= 10 km, use "9999"
        if weather.visibility_nm is not None:
            vis = weather.visibility_nm
            # Convert to meters (1 nm = 1852 meters)
            vis_m = vis * 1852
            
            # Validate minimum visibility (400 meters = ICAO minimum)
            if vis_m < 400:
                logger.warning(f"Visibility {vis} nm ({vis_m:.0f}m) is below minimum, using 400m")
                vis_m = 400
            
            if vis_m >= 10000:
                # >= 10 km: use "9999" (unlimited visibility)
                parts.append("9999")
            else:
                # Clamp to ICAO-style steps: 8000, 5000, 3000, 1600, 800, 400
                if vis_m >= 8000:
                    vis_value = 8000
                elif vis_m >= 5000:
                    vis_value = 5000
                elif vis_m >= 3000:
                    vis_value = 3000
                elif vis_m >= 1600:
                    vis_value = 1600
                elif vis_m >= 800:
                    vis_value = 800
                else:
                    vis_value = 400
                
                # Format as 4-digit meters (e.g., "8000", "0500")
                parts.append(f"{vis_value:04d}")
        else:
            parts.append("9999")  # Default: unlimited visibility
        
        # Weather phenomena (simplified)
        if weather.weather_tokens:
            # Map common weather tokens to METAR codes
            wx_codes = []
            for token in weather.weather_tokens:
                if "RA" in token.upper():
                    wx_codes.append("RA")
                elif "SN" in token.upper():
                    wx_codes.append("SN")
                elif "FG" in token.upper():
                    wx_codes.append("FG")
            if wx_codes:
                parts.append("".join(wx_codes[:2]))  # Max 2 weather codes
        
        # Clouds. OVC000/BKN000 etc. are often treated as invalid in FSX; use minimum 005 (500 ft).
        if weather.clouds:
            cloud_parts = []
            for cloud in weather.clouds[:3]:  # Max 3 cloud layers
                if isinstance(cloud, dict):
                    coverage = cloud.get('coverage', 'SCT')
                    base_ft = cloud.get('base_ft', 3000)
                    base_100ft = max(5, int(base_ft / 100))  # min 500 ft -> OVC005
                    cov_map = {
                        'FEW': 'FEW', 'SCT': 'SCT', 'BKN': 'BKN', 'OVC': 'OVC', 'CLR': 'SKC'
                    }
                    cov_code = cov_map.get(coverage, 'SCT')
                    cloud_parts.append(f"{cov_code}{base_100ft:03d}")
            if cloud_parts:
                parts.extend(cloud_parts)
        else:
            parts.append("SKC")
        
        # Temperature and dewpoint
        if weather.temperature_c is not None:
            temp = int(weather.temperature_c)
            dewp = int(weather.dewpoint_c) if weather.dewpoint_c is not None else temp - 5
            parts.append(f"{temp:02d}/{dewp:02d}")
        
        # QNH (pressure) - SimConnect accepts both Q#### (hPa) and A#### (inHg)
        # Use Q#### format (hPa) as it's more direct
        if weather.qnh_hpa is not None:
            qnh_hpa = weather.qnh_hpa
            # Validate QNH range (normal: 950-1050 hPa, extreme: 870-1080 hPa)
            if qnh_hpa < 870 or qnh_hpa > 1080:
                logger.warning(f"QNH value {qnh_hpa} hPa is out of normal range, using default 1013 hPa")
                qnh_hpa = 1013.25  # Standard sea level pressure
            # Format: Q followed by hPa value (e.g., Q1013)
            parts.append(f"Q{int(round(qnh_hpa))}")
        else:
            # Default QNH if missing
            parts.append("Q1013")  # Standard sea level pressure
        
        # Build final METAR
        metar = " ".join(parts)
        return metar
    
    def disconnect(self):
        """Disconnect from SimConnect."""
        if self.connected and self.hSimConnect:
            try:
                SimConnectDLL.SimConnect_Close(self.hSimConnect)
            except:
                pass
            self.connected = False
            logger.info("Disconnected from SimConnect")
