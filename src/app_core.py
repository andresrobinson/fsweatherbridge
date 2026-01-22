"""Core application logic."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from src.config import AppConfig
from src.data_manager import DataManager
from src.fsuipc_bridge import FSUIPCBridge, get_aircraft_state
from src.metar_parser import parse_metar
from src.stations import StationDatabase
from src.taf_parser import parse_taf
from src.weather_combiner import combine_weather
from src.weather_injector import DEVInjector, WeatherInjector
from src.weather_smoother import WeatherSmoother, WeatherState
from src.weather_sources import AviationWeatherSource, WeatherSource

logger = logging.getLogger(__name__)


class WeatherEngine:
    """Main weather processing engine."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.data_manager = DataManager()
        self.station_db = StationDatabase()
        self.weather_source: Optional[WeatherSource] = None
        self.fsuipc_bridge: Optional[FSUIPCBridge] = None
        self.weather_smoother = WeatherSmoother(config.smoothing)
        # Injector will be initialized in _initialize() based on available connections
        self.injector: Optional[WeatherInjector] = None
        
        # State
        self.current_stations: List[tuple] = []  # (Station, distance)
        self.current_metars: Dict[str, tuple] = {}  # icao -> (ParsedMETAR, timestamp)
        self.current_tafs: Dict[str, tuple] = {}  # icao -> (ParsedTAF, timestamp)
        self.last_update_time: Optional[float] = None
        self.last_metar_fetch: Dict[str, float] = {}  # icao -> last fetch timestamp
        self.last_taf_fetch: Dict[str, float] = {}  # icao -> last fetch timestamp
        self.last_injected_weather: Optional[WeatherState] = None  # Last successfully injected weather
        self.last_injection_time: Optional[float] = None  # Timestamp of last weather injection
        self.last_injection_success: Optional[bool] = None  # Last injection result (True/False/None)
        
        # Initialize components
        self._initialize()
    
    def _initialize(self) -> None:
        """Initialize components."""
        # Load persisted data first (stations and weather from files)
        self._load_persisted_data()
        
        # Initialize weather source based on config
        if self.config.weather_source.enabled:
            if self.config.weather_source.source_type == "aviationweather":
                self.weather_source = AviationWeatherSource(
                    cache_seconds=self.config.weather_source.cache_seconds
                )
            # Add other source types here as they're implemented
            # elif self.config.weather_source.source_type == "other":
            #     self.weather_source = OtherWeatherSource(...)
        
        # Initialize FSUIPC bridge
        if self.config.fsuipc.enabled:
            try:
                self.fsuipc_bridge = FSUIPCBridge(self.config.fsuipc)
                self.fsuipc_bridge.connect()
            except Exception as e:
                # If FSUIPC initialization fails, disable it and continue in DEV mode
                logger.warning(f"FSUIPC initialization failed: {e}")
                logger.info("Continuing in DEV mode (simulated aircraft data).")
                self.config.fsuipc.enabled = False
                self.config.fsuipc.dev_mode = True
                self.fsuipc_bridge = None
        
        # Initialize weather injector (use FSUIPC if available, otherwise DEV)
        if self.config.fsuipc.enabled and not self.config.fsuipc.dev_mode and self.fsuipc_bridge and self.fsuipc_bridge.is_connected():
            # Use FSUIPC for weather injection (more reliable than SimConnect)
            try:
                from src.weather_injector import FSUIPCWeatherInjector
                self.injector = FSUIPCWeatherInjector(
                    self.fsuipc_bridge, 
                    self.config.station_selection,
                    self.station_db  # Pass pre-loaded station database
                )
                logger.info("Using FSUIPC for weather injection")
            except (ImportError, RuntimeError, Exception) as e:
                logger.warning(f"FSUIPC weather injection not available: {e}")
                logger.info("Using DEV injector (weather will be logged only)")
                self.injector = DEVInjector()
        else:
            self.injector = DEVInjector()
    
    def _load_persisted_data(self) -> None:
        """Load stations and weather data from persisted files."""
        logger.info("Loading persisted data from files...")
        
        # Load stations from file
        stations_data = self.data_manager.load_stations()
        if stations_data:
            # Note: Station names should already be enhanced when downloaded/saved
            # Enhancement happens during startup in download_full_data_on_startup()
            # We can optionally enhance with CSV synchronously here if needed, but async enhancement
            # with online fallback happens during startup
            
            # Update station database with loaded stations
            for station_dict in stations_data:
                try:
                    from src.stations import Station
                    station = Station(
                        icao=station_dict["icao"],
                        lat=station_dict.get("lat", 0.0),
                        lon=station_dict.get("lon", 0.0),
                        name=station_dict.get("name", ""),
                        country=station_dict.get("country", ""),
                    )
                    self.station_db.stations[station.icao] = station
                except Exception as e:
                    logger.warning(f"Error loading station {station_dict.get('icao', 'unknown')}: {e}")
            logger.info(f"Loaded {len(stations_data)} stations from file")
        
        # Load METAR from file
        metars_data = self.data_manager.load_metar()
        if metars_data:
            for icao, raw_metar in metars_data.items():
                try:
                    parsed = parse_metar(raw_metar)
                    self.current_metars[icao.upper()] = (parsed, time.time())
                except Exception as e:
                    logger.warning(f"Error parsing stored METAR for {icao}: {e}")
            logger.info(f"Loaded {len(metars_data)} METAR reports from file")
        
        # Load TAF from file
        tafs_data = self.data_manager.load_taf()
        if tafs_data:
            for icao, raw_taf in tafs_data.items():
                try:
                    parsed = parse_taf(raw_taf)
                    self.current_tafs[icao.upper()] = (parsed, time.time())
                except Exception as e:
                    logger.warning(f"Error parsing stored TAF for {icao}: {e}")
            logger.info(f"Loaded {len(tafs_data)} TAF reports from file")
    
    async def update(self) -> Dict:
        """
        Perform one update cycle.
        
        Returns:
            Status dictionary
        """
        logger.debug("Update cycle started")
        status = {
            "success": False,
            "error": None,
            "aircraft_state": None,
            "stations": [],
            "weather_injected": False,
        }
        
        # Get aircraft state (with auto-reconnect if needed)
        if self.fsuipc_bridge:
            if not self.fsuipc_bridge.is_connected():
                # Try to reconnect if auto-reconnect is enabled
                if self.config.fsuipc.auto_reconnect and not self.config.fsuipc.dev_mode:
                    logger.info("FSUIPC disconnected, attempting to reconnect...")
                    if self.fsuipc_bridge.reconnect():
                        logger.info("FSUIPC reconnected successfully")
                    else:
                        logger.warning("FSUIPC reconnection failed")
            
            if self.fsuipc_bridge.is_connected():
                aircraft_dict = get_aircraft_state(self.fsuipc_bridge)
                if aircraft_dict:
                    status["aircraft_state"] = aircraft_dict
                    
                    # Update smoother freeze altitude
                    self.weather_smoother.set_freeze_altitude(aircraft_dict.get("alt_ft", 0))
                    
                    # Select stations
                    if not self.config.manual_weather.enabled:
                        self.current_stations = self.station_db.find_nearest_stations(
                            aircraft_dict["lat"],
                            aircraft_dict["lon"],
                            radius_nm=self.config.station_selection.radius_nm,
                            max_results=self.config.station_selection.max_stations,
                            fallback_to_global=self.config.station_selection.fallback_to_global,
                        )
                        status["stations"] = [
                            {
                                "icao": s.icao,
                                "name": s.name,
                                "distance_nm": dist,
                            }
                            for s, dist in self.current_stations
                        ]
                        if self.current_stations:
                            logger.debug(f"Selected {len(self.current_stations)} stations for weather injection")
                        else:
                            logger.warning(f"No stations found near aircraft position ({aircraft_dict['lat']:.4f}, {aircraft_dict['lon']:.4f})")
                else:
                    logger.debug("FSUIPC not connected, cannot get aircraft position")
            else:
                logger.debug("FSUIPC bridge not available")
        else:
            logger.debug("FSUIPC not enabled in config")
        
        # Handle manual weather mode
        if self.config.manual_weather.enabled:
            if self.config.manual_weather.mode == "station" and self.config.manual_weather.icao:
                # Use manual station
                station = self.station_db.get_station(self.config.manual_weather.icao)
                if station:
                    self.current_stations = [(station, 0.0)]
                    status["stations"] = [{
                        "icao": station.icao,
                        "name": station.name,
                        "distance_nm": 0.0,
                    }]
            elif self.config.manual_weather.mode == "report":
                # Use manual report (processed below)
                pass
        
        # Fetch weather if not frozen in manual mode
        if not (self.config.manual_weather.enabled and self.config.manual_weather.freeze):
            await self._fetch_weather()
        else:
            logger.debug("Weather fetch skipped: manual weather is frozen")
        
        # Process and inject weather (only if changed and enough time has passed)
        if self.current_stations or (self.config.manual_weather.enabled and self.config.manual_weather.mode == "report"):
            logger.debug(f"Processing weather: stations={len(self.current_stations)}, manual_mode={self.config.manual_weather.enabled}")
            weather = await self._process_weather()
            if weather:
                smoothed = self.weather_smoother.smooth(
                    weather,
                    aircraft_alt_ft=status["aircraft_state"]["alt_ft"] if status["aircraft_state"] else None,
                )
                
                # Log smoothing activity - show target vs smoothed to see transition progress
                target_wind = weather.get('wind_speed_kt')
                target_vis = weather.get('visibility_nm')
                wind_diff = abs(target_wind - smoothed.wind_speed_kt) if (target_wind is not None and smoothed.wind_speed_kt is not None) else None
                vis_diff = abs(target_vis - smoothed.visibility_nm) if (target_vis is not None and smoothed.visibility_nm is not None) else None
                
                is_big = getattr(smoothed, 'is_big_change', False)
                is_very_big = getattr(smoothed, 'is_very_big_change', False)
                
                # Always log if transitioning or if it's been a while since last log (every 10 seconds)
                current_time = time.time()
                should_log = (is_big or is_very_big or 
                             (wind_diff and wind_diff > 3.0) or 
                             (vis_diff and vis_diff > 1.0) or
                             (not hasattr(self, '_last_smoother_log_time') or 
                              (current_time - self._last_smoother_log_time) > 10.0))
                
                if should_log:
                    # Format values safely
                    wind_diff_str = f"{wind_diff:.1f}" if wind_diff is not None else "N/A"
                    vis_diff_str = f"{vis_diff:.1f}" if vis_diff is not None else "N/A"
                    vis_str = f"{smoothed.visibility_nm:.1f}" if smoothed.visibility_nm is not None else "N/A"
                    
                    logger.info(f"Smoother: wind={smoothed.wind_dir_deg}°/{smoothed.wind_speed_kt}kt (target: {target_wind}kt, diff: {wind_diff_str}kt), vis={vis_str}nm (target: {target_vis}nm, diff: {vis_diff_str}nm), is_big={is_big}, is_very_big={is_very_big}")
                    self._last_smoother_log_time = current_time
                
                # Check if we should inject weather:
                # 1. Weather must have changed (compared to last injected)
                # 2. At least METAR refresh interval must have passed since last injection
                #    (or shorter interval for big changes to allow smooth transitions)
                current_time = time.time()
                metar_refresh_interval = self.config.weather_source.metar_refresh_seconds
                
                # For big changes, inject more frequently to allow smooth transitions
                # Very big changes: inject every 5 seconds
                # Big changes: inject every 10 seconds
                # Normal changes: use normal METAR refresh interval (typically 60 seconds)
                is_very_big = getattr(smoothed, 'is_very_big_change', False)
                is_big = getattr(smoothed, 'is_big_change', False)
                
                # Also check if we detected a big change initially (even if smoothed state is now close)
                # This ensures we continue fast injection during the transition
                # First, check if we're still transitioning by comparing smoothed to target
                target_wind = weather.get('wind_speed_kt')
                target_vis = weather.get('visibility_nm')
                wind_diff = abs(target_wind - smoothed.wind_speed_kt) if (target_wind is not None and smoothed.wind_speed_kt is not None) else None
                vis_diff = abs(target_vis - smoothed.visibility_nm) if (target_vis is not None and smoothed.visibility_nm is not None) else None
                
                # Determine injection interval and transition state based on mode
                # MINIMUM injection interval: 10 seconds (to avoid excessive injections)
                MIN_INJECTION_INTERVAL = 10.0
                # BIG CHANGE injection interval: 30 seconds (for smooth progressive transitions)
                BIG_CHANGE_INTERVAL = 30.0
                
                still_transitioning = False
                if self.config.smoothing.transition_mode == "time_based":
                    # Time-based mode: use configured transition interval (already validated to be >= 10s)
                    injection_interval = max(self.config.smoothing.transition_interval_seconds, MIN_INJECTION_INTERVAL)
                    # Check if we're still transitioning (compare smoothed to target)
                    still_transitioning = (
                        (wind_diff is not None and wind_diff > self.config.smoothing.wind_speed_step_kt) or
                        (vis_diff is not None and vis_diff > (self.config.smoothing.visibility_step_m / 1852.0))
                    )
                    if still_transitioning:
                        logger.info(f"Time-based transition: injecting every {injection_interval:.0f}s (wind diff: {wind_diff:.1f}kt, vis diff: {vis_diff:.1f}nm)")
                else:
                    # Step-limited mode (original behavior)
                    if is_very_big:
                        injection_interval = BIG_CHANGE_INTERVAL  # 30 seconds for very big changes
                        still_transitioning = True
                        logger.info(f"Very big weather change detected - injecting every {BIG_CHANGE_INTERVAL:.0f} seconds for smooth progressive transition")
                    elif is_big:
                        injection_interval = BIG_CHANGE_INTERVAL  # 30 seconds for big changes
                        still_transitioning = True
                        logger.info(f"Big weather change detected - injecting every {BIG_CHANGE_INTERVAL:.0f} seconds for smooth progressive transition")
                    elif (wind_diff is not None and wind_diff > 3.0) or (vis_diff is not None and vis_diff > 1.0):
                        # Still transitioning - use big change interval to continue smooth transition
                        injection_interval = BIG_CHANGE_INTERVAL
                        still_transitioning = True
                        logger.info(f"Still transitioning (wind diff: {wind_diff:.1f}kt, vis diff: {vis_diff:.1f}nm) - injecting every {BIG_CHANGE_INTERVAL:.0f} seconds")
                    else:
                        injection_interval = max(metar_refresh_interval, MIN_INJECTION_INTERVAL)
                        still_transitioning = False
                
                time_since_last_injection = (current_time - self.last_injection_time) if self.last_injection_time else float('inf')
                weather_changed = self._has_weather_changed(smoothed)
                
                # During transitions, always inject if enough time has passed (even if change is small)
                # This ensures smooth transitions during large weather changes
                should_inject = False  # Initialize to False
                if still_transitioning and (time_since_last_injection >= injection_interval):
                    should_inject = True
                    logger.info(f"Injection approved (transitioning): {time_since_last_injection:.1f}s >= {injection_interval:.1f}s")
                elif still_transitioning and (time_since_last_injection < injection_interval):
                    logger.info(f"Injection skipped (transitioning): only {time_since_last_injection:.1f}s since last injection (need {injection_interval:.1f}s)")
                elif (is_big or is_very_big) and (time_since_last_injection >= injection_interval):
                    should_inject = True
                    logger.info(f"Injection approved (big change): {time_since_last_injection:.1f}s >= {injection_interval:.1f}s")
                elif (is_big or is_very_big) and (time_since_last_injection < injection_interval):
                    logger.info(f"Injection skipped (big change): only {time_since_last_injection:.1f}s since last injection (need {injection_interval:.1f}s)")
                else:
                    should_inject = weather_changed and (time_since_last_injection >= injection_interval)
                    if should_inject:
                        logger.info(f"Injection approved: weather changed and {time_since_last_injection:.1f}s >= {injection_interval:.1f}s")
                    elif not weather_changed and time_since_last_injection >= injection_interval:
                        # Log when injection is skipped due to no change (but time has passed)
                        logger.info(f"Injection skipped: weather has not changed (last injected: wind={self.last_injected_weather.wind_speed_kt if self.last_injected_weather else 'None'}kt, current: wind={smoothed.wind_speed_kt}kt)")
                    elif time_since_last_injection < injection_interval:
                        logger.debug(f"Injection skipped: only {time_since_last_injection:.1f}s since last injection (need {injection_interval:.1f}s)")
                
                if should_inject:
                    # Format weather values safely, handling None values
                    wind_dir = f"{smoothed.wind_dir_deg:.0f}" if smoothed.wind_dir_deg is not None else "N/A"
                    wind_speed = f"{smoothed.wind_speed_kt:.1f}" if smoothed.wind_speed_kt is not None else "N/A"
                    qnh = f"{smoothed.qnh_hpa:.1f}" if smoothed.qnh_hpa is not None else "N/A"
                    logger.info(f"Weather injection: Wind {wind_dir}°/{wind_speed}kt, QNH {qnh}hPa")
                    
                    # If values are None, log a warning with more details
                    if smoothed.wind_dir_deg is None or smoothed.wind_speed_kt is None or smoothed.qnh_hpa is None:
                        logger.warning(f"WeatherState has None values - this indicates METAR data wasn't extracted properly")
                        logger.warning(f"  Current stations: {[s.icao for s, _ in self.current_stations]}")
                        logger.warning(f"  METARs loaded: {len(self.current_metars)}")
                        if self.current_stations:
                            primary_icao = self.current_stations[0][0].icao
                            logger.warning(f"  Primary station {primary_icao} in METARs: {primary_icao in self.current_metars}")
                            if primary_icao in self.current_metars:
                                metar_obj, _ = self.current_metars[primary_icao]
                                logger.warning(f"  METAR object: valid={getattr(metar_obj, 'valid', 'unknown')}, wind={metar_obj.wind_dir_deg}/{metar_obj.wind_speed_kt}, qnh={metar_obj.qnh_hpa}")
                    # Inject METARs for nearby stations and let FSX blend them
                    # This provides smooth transitions as the aircraft moves
                    has_multi_inject = hasattr(self.injector, 'inject_station_metars')
                    if has_multi_inject and self.current_stations:
                        logger.debug(f"Using multi-station injection (has method: {has_multi_inject}, stations: {len(self.current_stations)})")
                        # Prepare list of stations with their METARs
                        stations_with_metars = []
                        for station, distance_nm in self.current_stations:
                            icao = station.icao
                            if icao in self.current_metars:
                                metar, _ = self.current_metars[icao]
                                if metar and getattr(metar, 'valid', False):
                                    stations_with_metars.append((icao, metar, distance_nm))
                        
                        if stations_with_metars:
                            # Use config max_stations if available, otherwise default to 5
                            max_stations = self.config.station_selection.max_stations if self.config.station_selection else 5
                            if self.injector.inject_station_metars(stations_with_metars, max_stations=max_stations):
                                status["weather_injected"] = True
                                status["success"] = True
                                self.last_injected_weather = smoothed
                                self.last_injection_time = current_time
                                self.last_injection_success = True
                                logger.info("Weather injection successful (injected multiple station METARs for FSX blending)")
                            else:
                                self.last_injection_success = False
                                logger.warning("Weather injection failed")
                        else:
                            logger.warning("No valid METARs found for nearby stations")
                    else:
                        # Fallback to single-station injection
                        if not has_multi_inject:
                            logger.debug("Multi-station injection not available, using single-station fallback")
                        elif not self.current_stations:
                            logger.debug("No current stations available, using single-station fallback")
                        aircraft_lat = status["aircraft_state"]["lat"] if status["aircraft_state"] else None
                        aircraft_lon = status["aircraft_state"]["lon"] if status["aircraft_state"] else None
                        if self.injector.inject_weather(smoothed, aircraft_lat, aircraft_lon):
                            status["weather_injected"] = True
                            status["success"] = True
                            self.last_injected_weather = smoothed
                            self.last_injection_time = current_time
                            self.last_injection_success = True
                            logger.info("Weather injection successful")
                        else:
                            self.last_injection_success = False
                            logger.warning("Weather injection failed")
                else:
                    # Log why injection was skipped (debug level to avoid spam)
                    if not weather_changed:
                        logger.debug("Weather injection skipped: no changes detected")
                    elif time_since_last_injection < metar_refresh_interval:
                        logger.debug(f"Weather injection skipped: only {time_since_last_injection:.1f}s since last injection (need {metar_refresh_interval}s)")
        else:
            # Log why weather processing is skipped
            if not self.current_stations and not (self.config.manual_weather.enabled and self.config.manual_weather.mode == "report"):
                logger.debug(f"Weather processing skipped: no stations selected (current_stations={len(self.current_stations)}, manual_mode={self.config.manual_weather.enabled})")
        
        self.last_update_time = time.time()
        return status
    
    async def _fetch_weather(self) -> None:
        """Fetch METAR and TAF for current stations using cache files."""
        if not self.config.weather_source.enabled:
            return
        
        if self.config.manual_weather.enabled and self.config.manual_weather.mode == "report":
            # Manual report mode - skip fetching
            return
        
        current_time = time.time()
        
        # Check if we should refresh from cache files (based on file age)
        # METAR cache is updated every minute, TAF cache every 10 minutes
        metar_refresh_interval = self.config.weather_source.metar_refresh_seconds
        taf_refresh_interval = self.config.weather_source.taf_refresh_seconds
        
        # Check METAR file age
        should_refresh_metar = False
        if self.data_manager.METAR_FILE.exists():
            try:
                with open(self.data_manager.METAR_FILE, "r", encoding="utf-8") as f:
                    import json
                    data = json.load(f)
                    timestamp = data.get("timestamp", 0)
                    age_seconds = current_time - timestamp
                    should_refresh_metar = age_seconds >= metar_refresh_interval
            except:
                should_refresh_metar = True
        else:
            should_refresh_metar = True
        
        # Check TAF file age
        should_refresh_taf = False
        if self.data_manager.TAF_FILE.exists():
            try:
                with open(self.data_manager.TAF_FILE, "r", encoding="utf-8") as f:
                    import json
                    data = json.load(f)
                    timestamp = data.get("timestamp", 0)
                    age_seconds = current_time - timestamp
                    should_refresh_taf = age_seconds >= taf_refresh_interval
            except:
                should_refresh_taf = True
        else:
            should_refresh_taf = True
        
        # Download METAR cache if needed
        if should_refresh_metar:
            logger.info("METAR cache file is stale, downloading from AviationWeather.gov cache...")
            try:
                metars = await self.data_manager.download_full_metar()
                if metars:
                    # Save to file
                    self.data_manager.save_metar(metars, archive=True)
                    
                    # Update in-memory cache for all downloaded METARs
                    updated_count = 0
                    for icao, raw_metar in metars.items():
                        try:
                            parsed = parse_metar(raw_metar)
                            self.current_metars[icao.upper()] = (parsed, current_time)
                            self.last_metar_fetch[icao.upper()] = current_time
                            updated_count += 1
                            
                            # Debug log for specific stations (only in debug mode)
                            if icao.upper() in ["SAEZ", "CYPR"]:
                                logger.debug(f"Parsed {icao.upper()} METAR: wind={parsed.wind_dir_deg}°/{parsed.wind_speed_kt}kt, vis={parsed.visibility_nm}nm, qnh={parsed.qnh_hpa}hPa")
                        except Exception as e:
                            logger.warning(f"Error parsing METAR for {icao}: {e}")
                    
                    logger.info(f"Updated {updated_count} METAR reports from cache file")
                else:
                    logger.warning("No METAR data downloaded from cache")
            except Exception as e:
                logger.error(f"Error downloading METAR cache: {e}", exc_info=True)
        
        # Download TAF cache if needed
        if should_refresh_taf:
            logger.info("TAF cache file is stale, downloading from AviationWeather.gov cache...")
            try:
                tafs = await self.data_manager.download_full_taf()
                if tafs:
                    # Save to file
                    self.data_manager.save_taf(tafs, archive=True)
                    
                    # Update in-memory cache for all downloaded TAFs
                    updated_count = 0
                    for icao, raw_taf in tafs.items():
                        try:
                            parsed = parse_taf(raw_taf)
                            self.current_tafs[icao.upper()] = (parsed, current_time)
                            self.last_taf_fetch[icao.upper()] = current_time
                            updated_count += 1
                        except Exception as e:
                            logger.warning(f"Error parsing TAF for {icao}: {e}")
                    
                    logger.info(f"Updated {updated_count} TAF reports from cache file")
                else:
                    logger.warning("No TAF data downloaded from cache")
            except Exception as e:
                logger.error(f"Error downloading TAF cache: {e}", exc_info=True)
    
    async def _process_weather(self) -> Optional[Dict]:
        """Process weather from current stations."""
        # Handle manual report mode
        if self.config.manual_weather.enabled and self.config.manual_weather.mode == "report":
            metar = None
            taf = None
            
            if self.config.manual_weather.raw_metar:
                metar = parse_metar(self.config.manual_weather.raw_metar)
            
            if self.config.manual_weather.raw_taf:
                taf = parse_taf(self.config.manual_weather.raw_taf)
            
            combined = combine_weather(
                metar,
                taf,
                self.config.weather_combining,
            )
            return combined.to_dict()
        
        # Use station data
        if not self.current_stations:
            logger.debug("No current stations selected - cannot process weather")
            return None
        
        # If only one station, use simple approach
        if len(self.current_stations) == 1:
            primary_station, _ = self.current_stations[0]
            icao = primary_station.icao
            
            # Get METAR and TAF
            metar = None
            taf = None
            metar_age = None
            
            if icao in self.current_metars:
                metar, metar_timestamp = self.current_metars[icao]
                metar_age = time.time() - metar_timestamp
                raw_metar = getattr(metar, 'raw', 'N/A')
                logger.debug(f"Found METAR for {icao}: wind={metar.wind_dir_deg}°/{metar.wind_speed_kt}kt, QNH={metar.qnh_hpa}hPa, vis={metar.visibility_nm}nm")
                if not getattr(metar, 'valid', True):
                    logger.warning(f"METAR for {icao} is marked as invalid - weather may not be extracted correctly")
            else:
                logger.warning(f"No METAR found for station {icao} in current_metars (have {len(self.current_metars)} METARs loaded)")
                # Check if CYRT exists with different case
                cyrt_variants = [k for k in self.current_metars.keys() if k.upper() == icao.upper()]
                if cyrt_variants:
                    logger.warning(f"Found {icao} with different case: {cyrt_variants[0]}")
                logger.debug(f"Available METAR stations (first 20): {list(self.current_metars.keys())[:20]}")
            
            if icao in self.current_tafs:
                taf, _ = self.current_tafs[icao]
                logger.debug(f"Found TAF for {icao}")
            
            # Combine weather
            combined = combine_weather(
                metar,
                taf,
                self.config.weather_combining,
                metar_age_seconds=metar_age,
            )
            
            logger.debug(f"Combined weather for {icao}: source={combined.source}, wind={combined.wind_dir_deg}°/{combined.wind_speed_kt}kt, QNH={combined.qnh_hpa}hPa")
            if combined.source == "none":
                logger.warning(f"No valid weather data for {icao} - METAR valid={getattr(metar, 'valid', 'unknown') if metar else 'N/A'}, TAF valid={getattr(taf, 'valid', 'unknown') if taf else 'N/A'}")
            
            return combined.to_dict()
        
        # Multiple stations: use nearest station's raw METAR (FSX will blend)
        # Since we're injecting raw station METARs and letting FSX blend, we should
        # use the nearest station's raw data for smoothing/status, not blended data
        if self.current_stations:
            nearest_station, _ = self.current_stations[0]  # Closest station
            icao = nearest_station.icao
            
            # Get METAR and TAF for nearest station
            metar = None
            taf = None
            metar_age = None
            
            if icao in self.current_metars:
                metar, metar_timestamp = self.current_metars[icao]
                metar_age = time.time() - metar_timestamp
            
            if icao in self.current_tafs:
                taf, _ = self.current_tafs[icao]
            
            # Combine weather from nearest station (METAR + TAF)
            combined = combine_weather(
                metar,
                taf,
                self.config.weather_combining,
                metar_age_seconds=metar_age,
            )
            
            logger.debug(f"Using nearest station {icao} weather for smoothing/status (FSX will blend multiple stations)")
            return combined.to_dict()
        
        return None
    
    def _blend_weather_from_stations(self) -> Optional[Dict]:
        """
        Blend weather from multiple stations using distance-weighted interpolation.
        
        Closer stations have more influence than distant ones.
        """
        if not self.current_stations:
            return None
        
        # Collect weather data from all stations
        station_weathers = []
        total_weight = 0.0
        
        for station, distance_nm in self.current_stations:
            icao = station.icao
            
            # Get METAR and TAF for this station
            metar = None
            taf = None
            metar_age = None
            
            if icao in self.current_metars:
                metar, metar_timestamp = self.current_metars[icao]
                metar_age = time.time() - metar_timestamp
            
            if icao in self.current_tafs:
                taf, _ = self.current_tafs[icao]
            
            # Combine weather for this station
            combined = combine_weather(
                metar,
                taf,
                self.config.weather_combining,
                metar_age_seconds=metar_age,
            )
            
            # Calculate weight: inverse distance squared (closer = much more weight)
            # Add small epsilon to avoid division by zero
            weight = 1.0 / ((distance_nm + 0.1) ** 2)
            total_weight += weight
            
            station_weathers.append({
                'weather': combined,
                'weight': weight,
                'distance': distance_nm,
                'icao': icao,
            })
        
        if not station_weathers or total_weight == 0:
            return None
        
        # Normalize weights
        for sw in station_weathers:
            sw['weight'] /= total_weight
        
        # Blend weather parameters
        blended = {
            'wind_dir_deg': None,
            'wind_speed_kt': None,
            'wind_gust_kt': None,
            'visibility_nm': None,
            'temperature_c': None,
            'dewpoint_c': None,
            'qnh_hpa': None,
            'clouds': [],
            'weather_tokens': [],
            'source': 'blended',
            'metar_used': any(sw['weather'].metar_used for sw in station_weathers),
            'taf_used': any(sw['weather'].taf_used for sw in station_weathers),
        }
        
        # Blend wind direction (circular mean)
        wind_dirs = []
        wind_weights = []
        for sw in station_weathers:
            if sw['weather'].wind_dir_deg is not None:
                wind_dirs.append(sw['weather'].wind_dir_deg)
                wind_weights.append(sw['weight'])
        
        if wind_dirs:
            # Convert to radians, calculate weighted circular mean
            import math
            sin_sum = sum(w * math.sin(math.radians(d)) for d, w in zip(wind_dirs, wind_weights))
            cos_sum = sum(w * math.cos(math.radians(d)) for d, w in zip(wind_dirs, wind_weights))
            if sin_sum != 0 or cos_sum != 0:
                blended['wind_dir_deg'] = math.degrees(math.atan2(sin_sum, cos_sum)) % 360
        
        # Blend wind speed (weighted average)
        wind_speeds = [(sw['weather'].wind_speed_kt, sw['weight']) 
                      for sw in station_weathers 
                      if sw['weather'].wind_speed_kt is not None]
        if wind_speeds:
            blended['wind_speed_kt'] = sum(s * w for s, w in wind_speeds)
        
        # Blend wind gust (weighted average)
        wind_gusts = [(sw['weather'].wind_gust_kt, sw['weight']) 
                     for sw in station_weathers 
                     if sw['weather'].wind_gust_kt is not None]
        if wind_gusts:
            blended['wind_gust_kt'] = sum(g * w for g, w in wind_gusts)
        
        # Blend QNH (weighted average)
        qnhs = [(sw['weather'].qnh_hpa, sw['weight'], sw['icao']) 
               for sw in station_weathers 
               if sw['weather'].qnh_hpa is not None]
        if qnhs:
            blended['qnh_hpa'] = sum(q * w for q, w, _ in qnhs)
            # Note: Blending is only used for legacy/fallback - we now inject raw station METARs
            # and let FSX do the blending. This blending is kept for backward compatibility.
            # Log at debug level since we're not using blended data for injection anymore
            qnh_details = ", ".join([f"{icao}: {q:.1f}hPa (weight: {w:.3f})" for q, w, icao in qnhs])
            logger.debug(f"Blending QNH from {len(qnhs)} stations: {qnh_details} -> {blended['qnh_hpa']:.1f}hPa (for status only - injection uses raw station METARs)")
        
        # Blend visibility (weighted average)
        visibilities = [(sw['weather'].visibility_nm, sw['weight']) 
                       for sw in station_weathers 
                       if sw['weather'].visibility_nm is not None]
        if visibilities:
            blended['visibility_nm'] = sum(v * w for v, w in visibilities)
        
        # Blend temperature (weighted average)
        temps = [(sw['weather'].temperature_c, sw['weight']) 
                for sw in station_weathers 
                if sw['weather'].temperature_c is not None]
        if temps:
            blended['temperature_c'] = sum(t * w for t, w in temps)
        
        # Blend dewpoint (weighted average)
        dewpoints = [(sw['weather'].dewpoint_c, sw['weight']) 
                    for sw in station_weathers 
                    if sw['weather'].dewpoint_c is not None]
        if dewpoints:
            blended['dewpoint_c'] = sum(d * w for d, w in dewpoints)
        
        # For clouds, use the closest station's clouds (too complex to blend)
        if station_weathers:
            closest = min(station_weathers, key=lambda sw: sw['distance'])
            blended['clouds'] = closest['weather'].clouds.copy() if closest['weather'].clouds else []
        
        # For weather tokens, collect from all stations (union)
        all_tokens = set()
        for sw in station_weathers:
            if sw['weather'].weather_tokens:
                all_tokens.update(sw['weather'].weather_tokens)
        blended['weather_tokens'] = list(all_tokens)
        
        station_list = [sw['icao'] for sw in station_weathers]
        distance_list = [f"{sw['distance']:.1f}nm" for sw in station_weathers]
        # Note: Blending is only used for legacy/fallback - we now inject raw station METARs
        # and let FSX do the blending. This blending is kept for backward compatibility.
        logger.debug(f"Blended weather from {len(station_weathers)} stations: {station_list} (distances: {distance_list}) - for status only, injection uses raw station METARs")
        
        return blended
    
    def _has_weather_changed(self, new_weather: WeatherState) -> bool:
        """
        Check if weather has changed significantly compared to last injected weather.
        
        Args:
            new_weather: New weather state to compare
            
        Returns:
            True if weather has changed significantly, False otherwise
        """
        if self.last_injected_weather is None:
            # No previous weather injected, so this is a change
            return True
        
        old = self.last_injected_weather
        new = new_weather
        
        # Tolerance thresholds for considering weather "changed"
        # These should be larger than smoothing thresholds to avoid unnecessary injections
        WIND_DIR_THRESHOLD = 5.0  # degrees
        WIND_SPEED_THRESHOLD = 2.0  # knots
        QNH_THRESHOLD = 0.5  # hPa
        VISIBILITY_THRESHOLD = 0.5  # nm
        
        # Check wind direction (handle circular nature)
        if old.wind_dir_deg is not None and new.wind_dir_deg is not None:
            diff = abs(new.wind_dir_deg - old.wind_dir_deg)
            # Handle wrap-around (e.g., 359° vs 1°)
            if diff > 180:
                diff = 360 - diff
            if diff > WIND_DIR_THRESHOLD:
                return True
        elif old.wind_dir_deg != new.wind_dir_deg:  # One is None, other isn't
            return True
        
        # Check wind speed
        if old.wind_speed_kt is not None and new.wind_speed_kt is not None:
            if abs(new.wind_speed_kt - old.wind_speed_kt) > WIND_SPEED_THRESHOLD:
                return True
        elif old.wind_speed_kt != new.wind_speed_kt:
            return True
        
        # Check QNH
        if old.qnh_hpa is not None and new.qnh_hpa is not None:
            if abs(new.qnh_hpa - old.qnh_hpa) > QNH_THRESHOLD:
                return True
        elif old.qnh_hpa != new.qnh_hpa:
            return True
        
        # Check visibility
        if old.visibility_nm is not None and new.visibility_nm is not None:
            if abs(new.visibility_nm - old.visibility_nm) > VISIBILITY_THRESHOLD:
                return True
        elif old.visibility_nm != new.visibility_nm:
            return True
        
        # Check temperature (significant changes only)
        if old.temperature_c is not None and new.temperature_c is not None:
            if abs(new.temperature_c - old.temperature_c) > 2.0:  # 2°C threshold
                return True
        elif old.temperature_c != new.temperature_c:
            return True
        
        # Check clouds (simple comparison - if different, it's a change)
        if old.clouds != new.clouds:
            return True
        
        # Check weather tokens (if different, it's a change)
        if set(old.weather_tokens) != set(new.weather_tokens):
            return True
        
        # No significant changes detected
        return False
    
    def get_status(self) -> Dict:
        """Get current status."""
        # Get weather update info for each station
        weather_updates = []
        for station, dist in self.current_stations:
            icao = station.icao
            metar_info = None
            taf_info = None
            
            if icao in self.current_metars:
                metar, timestamp = self.current_metars[icao]
                metar_info = {
                    "raw": metar.raw if hasattr(metar, 'raw') else str(metar),
                    "timestamp": timestamp,
                    "age_seconds": time.time() - timestamp,
                }
            
            if icao in self.current_tafs:
                taf, timestamp = self.current_tafs[icao]
                taf_info = {
                    "raw": taf.raw if hasattr(taf, 'raw') else str(taf),
                    "timestamp": timestamp,
                    "age_seconds": time.time() - timestamp,
                }
            
            weather_updates.append({
                "icao": icao,
                "name": station.name,
                "distance_nm": dist,
                "metar": metar_info,
                "taf": taf_info,
            })
        
        # Get data statistics
        stations_count = len(self.station_db.stations)
        metars_count = len(self.current_metars)
        tafs_count = len(self.current_tafs)
        
        # Get file statistics
        stations_file_age = None
        metar_file_age = None
        taf_file_age = None
        
        if self.data_manager.STATIONS_FILE.exists():
            try:
                import json
                with open(self.data_manager.STATIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    timestamp = data.get("timestamp", 0)
                    stations_file_age = time.time() - timestamp
            except:
                pass
        
        if self.data_manager.METAR_FILE.exists():
            try:
                with open(self.data_manager.METAR_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    timestamp = data.get("timestamp", 0)
                    metar_file_age = time.time() - timestamp
            except:
                pass
        
        if self.data_manager.TAF_FILE.exists():
            try:
                with open(self.data_manager.TAF_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    timestamp = data.get("timestamp", 0)
                    taf_file_age = time.time() - timestamp
            except:
                pass
        
        # Get stable FSUIPC connection status (use cached status from is_connected() to prevent flickering)
        fsuipc_connected = False
        if self.fsuipc_bridge:
            try:
                # Use is_connected() which has built-in caching to prevent flickering
                fsuipc_connected = self.fsuipc_bridge.is_connected()
            except Exception as e:
                logger.debug(f"Error checking FSUIPC connection status: {e}")
                fsuipc_connected = False
        
        return {
            "fsuipc_connected": fsuipc_connected,
            "last_injection_success": self.last_injection_success,  # Last injection result
            "last_injection_time": self.last_injection_time,  # Last injection timestamp
            "data_statistics": {
                "stations": {
                    "loaded": stations_count,
                    "file_age_seconds": stations_file_age,
                },
                "metars": {
                    "loaded": metars_count,
                    "file_age_seconds": metar_file_age,
                },
                "tafs": {
                    "loaded": tafs_count,
                    "file_age_seconds": taf_file_age,
                },
            },
            "stations": [
                {
                    "icao": s.icao,
                    "name": s.name,
                    "distance_nm": dist,
                }
                for s, dist in self.current_stations
            ],
            "weather_updates": weather_updates,
            "last_update": self.last_update_time,
            "manual_mode": self.config.manual_weather.enabled,
        }
    
    def get_weather_for_icao(self, icao: str) -> Optional[Dict]:
        """Get weather data for a specific ICAO code."""
        icao_upper = icao.upper().strip()
        
        result = {
            "icao": icao_upper,
            "station": None,
            "metar": None,
            "taf": None,
        }
        
        # Get station info
        station = self.station_db.get_station(icao_upper)
        if station:
            result["station"] = station.to_dict()
        
        # Debug: log what's in the dictionaries
        logger.debug(f"Looking up {icao_upper}: METAR keys={list(self.current_metars.keys())}, TAF keys={list(self.current_tafs.keys())}")
        
        # Get METAR - try exact match first, then case-insensitive
        metar_found = False
        if icao_upper in self.current_metars:
            metar_found = True
            metar, timestamp = self.current_metars[icao_upper]
        else:
            # Try case-insensitive lookup
            for key in self.current_metars.keys():
                if key.upper() == icao_upper:
                    metar, timestamp = self.current_metars[key]
                    metar_found = True
                    logger.debug(f"Found METAR with case-insensitive match: {key} -> {icao_upper}")
                    break
        
        if metar_found:
            result["metar"] = {
                "raw": metar.raw if hasattr(metar, 'raw') else str(metar),
                "parsed": metar.to_dict() if hasattr(metar, 'to_dict') else None,
                "timestamp": timestamp,
                "age_seconds": time.time() - timestamp,
            }
        
        # Get TAF - try exact match first, then case-insensitive
        taf_found = False
        if icao_upper in self.current_tafs:
            taf_found = True
            taf, timestamp = self.current_tafs[icao_upper]
        else:
            # Try case-insensitive lookup
            for key in self.current_tafs.keys():
                if key.upper() == icao_upper:
                    taf, timestamp = self.current_tafs[key]
                    taf_found = True
                    logger.info(f"Found TAF with case-insensitive match: {key} -> {icao_upper}")
                    break
        
        if taf_found:
            result["taf"] = {
                "raw": taf.raw if hasattr(taf, 'raw') else str(taf),
                "parsed": taf.to_dict() if hasattr(taf, 'to_dict') else None,
                "timestamp": timestamp,
                "age_seconds": time.time() - timestamp,
            }
        
        return result
    
    def shutdown(self) -> None:
        """Shutdown engine."""
        if self.fsuipc_bridge:
            self.fsuipc_bridge.disconnect()
