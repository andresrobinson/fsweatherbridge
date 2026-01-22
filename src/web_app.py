"""FastAPI web application."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.app_core import WeatherEngine
from src.config import (
    AppConfig,
    FSUIPCConfig,
    ManualWeatherConfig,
    SmoothingConfig,
    StationSelectionConfig,
    WeatherCombiningConfig,
    WeatherSourceConfig,
    WebUIConfig,
)
from src.fsuipc_bridge import get_aircraft_state as get_aircraft_state_from_bridge

# Check if airportsdata is available
try:
    import airportsdata
    AIRPORTS_DATA_AVAILABLE = True
except ImportError:
    AIRPORTS_DATA_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress noisy asyncio callback errors on Windows (harmless connection cleanup errors)
# These occur when WebSocket connections are closed abruptly on Windows
asyncio_logger = logging.getLogger('asyncio')
asyncio_logger.setLevel(logging.CRITICAL)  # Only show critical asyncio errors

# Also suppress specific error messages
class AsyncioErrorFilter(logging.Filter):
    """Filter to suppress harmless asyncio connection errors on Windows."""
    def filter(self, record):
        msg = record.getMessage()
        # Suppress ConnectionResetError in _call_connection_lost
        if 'ConnectionResetError' in msg:
            if any(x in msg for x in ['_call_connection_lost', 'SHUT_RDWR', 'WinError 10054', '10054']):
                return False
        # Suppress ProactorBasePipeTransport errors
        if 'ProactorBasePipeTransport' in msg:
            if any(x in msg for x in ['connection_lost', '_call_connection_lost', 'Exception in callback']):
                return False
        # Suppress callback errors related to connection cleanup
        if 'Exception in callback' in msg:
            if any(x in msg for x in ['ProactorBasePipeTransport', '_call_connection_lost', 'connection_lost']):
                return False
        # Suppress specific Windows socket errors
        if 'WinError 10054' in msg or 'Foi forçado o cancelamento' in msg:
            if any(x in msg for x in ['connection', 'socket', 'SHUT']):
                return False
        return True

# Apply filter to asyncio logger and root logger
asyncio_logger.addFilter(AsyncioErrorFilter())
root_logger = logging.getLogger()
root_logger.addFilter(AsyncioErrorFilter())

# In-memory log storage for web UI
log_buffer = []
MAX_LOG_ENTRIES = 1000

class WebLogHandler(logging.Handler):
    """Custom log handler that stores logs in memory."""
    def emit(self, record):
        log_entry = {
            'timestamp': record.created * 1000,  # Convert to milliseconds
            'level': record.levelname,
            'message': self.format(record),
        }
        log_buffer.append(log_entry)
        # Keep only last MAX_LOG_ENTRIES
        if len(log_buffer) > MAX_LOG_ENTRIES:
            log_buffer.pop(0)

# Add custom handler to root logger
web_log_handler = WebLogHandler()
web_log_handler.setFormatter(logging.Formatter('%(message)s'))
logging.getLogger().addHandler(web_log_handler)

app = FastAPI(title="FSX Weather Bridge")

# Global exception handler to ensure JSON errors
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle all exceptions and return JSON."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error": True}
        )
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "error": True}
    )

# Global state
engine: Optional[WeatherEngine] = None
config: Optional[AppConfig] = None
update_task: Optional[asyncio.Task] = None
websocket_clients: List[WebSocket] = []

# Simple in-memory cache for API responses
class APICache:
    """Simple in-memory cache with TTL."""
    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key -> (data, timestamp, ttl)
    
    def get(self, key: str):
        """Get cached data if not expired."""
        if key not in self._cache:
            return None
        data, timestamp, ttl = self._cache[key]
        if time.time() - timestamp > ttl:
            del self._cache[key]
            return None
        return data
    
    def set(self, key: str, data, ttl: float = 300.0):
        """Cache data with TTL (default 5 minutes)."""
        self._cache[key] = (data, time.time(), ttl)
    
    def invalidate(self, key: str = None):
        """Invalidate cache entry(ies). If key is None, invalidate all."""
        if key is None:
            self._cache.clear()
        elif key in self._cache:
            del self._cache[key]
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all cache keys matching pattern."""
        keys_to_remove = [k for k in self._cache.keys() if pattern in k]
        for k in keys_to_remove:
            del self._cache[k]

api_cache = APICache()

# Static files
static_dir = Path(__file__).parent.parent / "static"
templates_dir = Path(__file__).parent.parent / "templates"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class SettingsUpdate(BaseModel):
    """Settings update model."""
    weather_source: Optional[Dict] = None
    weather_combining: Optional[Dict] = None
    smoothing: Optional[Dict] = None
    station_selection: Optional[Dict] = None
    manual_weather: Optional[Dict] = None
    fsuipc: Optional[Dict] = None
    web_ui: Optional[Dict] = None


class ManualWeatherRequest(BaseModel):
    """Manual weather request."""
    mode: str  # "station" or "report"
    icao: Optional[str] = None
    raw_metar: Optional[str] = None
    raw_taf: Optional[str] = None
    freeze: bool = False


class InjectRawMetarRequest(BaseModel):
    """Request body for raw METAR injection."""
    metar: str


async def airport_data_update_loop():
    """Background task to update airport data from AviationWeather.gov weekly (silent, non-blocking)."""
    global engine
    if not engine:
        return
    
    # Load existing cache on startup (silent, no update)
    try:
        if not engine.data_manager.airport_data_cache:
            engine.data_manager.airport_data_cache = engine.data_manager.load_airport_data()
    except Exception as e:
        logger.debug(f"Error loading airport data cache on startup: {e}")
    
    # Wait before first check (don't update immediately on startup)
    await asyncio.sleep(3600)  # Wait 1 hour after startup before checking
    
    while True:
        try:
            if engine.data_manager.should_refresh_airport_data():
                # Update silently in background (use debug level for update messages)
                logger.debug("Starting weekly airport data update from AviationWeather.gov (silent background task)...")
                await engine.data_manager.update_airport_data_from_aviationweather()
                # Reload cache after update
                engine.data_manager.airport_data_cache = engine.data_manager.load_airport_data()
                logger.debug("Airport data update completed (silent background task).")
            else:
                # Just ensure cache is loaded
                if not engine.data_manager.airport_data_cache:
                    engine.data_manager.airport_data_cache = engine.data_manager.load_airport_data()
        except Exception as e:
            logger.debug(f"Error in airport data update loop: {e}", exc_info=True)
        
        # Check once per day
        await asyncio.sleep(86400)  # 24 hours


@app.on_event("startup")
async def startup():
    """Initialize application on startup."""
    global engine, config, update_task
    
    logger.info("FastAPI startup event triggered - initializing WeatherEngine...")
    
    # Set custom exception handler to suppress harmless Windows connection errors
    def custom_exception_handler(loop, context):
        """Suppress harmless Windows WebSocket connection cleanup errors."""
        exception = context.get('exception')
        message = str(context.get('message', ''))
        
        # Suppress ConnectionResetError from WebSocket cleanup on Windows
        if exception and isinstance(exception, ConnectionResetError):
            if '10054' in str(exception) or 'SHUT_RDWR' in message or '_call_connection_lost' in message:
                return  # Suppress this harmless error
        
        # Suppress ProactorBasePipeTransport callback errors
        if 'ProactorBasePipeTransport' in message and '_call_connection_lost' in message:
            return  # Suppress this harmless error
        
        # Suppress callback errors with connection reset
        if 'Exception in callback' in message:
            if 'ProactorBasePipeTransport' in message or '_call_connection_lost' in message:
                if exception and isinstance(exception, ConnectionResetError):
                    return  # Suppress this harmless error
        
        # Log other exceptions normally (but don't print to stderr)
        if exception:
            logger.debug(f"Event loop exception: {message}", exc_info=exception)
        else:
            logger.debug(f"Event loop message: {message}")
    
    # Get the current event loop and set custom handler
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(custom_exception_handler)
    except RuntimeError:
        # No running loop yet - this shouldn't happen in startup, but handle it
        pass
    
    # Load configuration
    config = AppConfig.load()
    
    # Initialize engine (this will load persisted data)
    engine = WeatherEngine(config)
    logger.info("WeatherEngine created successfully")
    
    # Download full data on startup if needed
    await download_full_data_on_startup()
    logger.info("Startup data download completed")
    
    # Start update loop
    update_task = asyncio.create_task(update_loop())
    logger.info("Update loop task started")
    
    # Start background airport data update task (runs weekly)
    airport_update_task = asyncio.create_task(airport_data_update_loop())
    logger.info("Airport data update task started")
    
    logger.info("FSX Weather Bridge started and ready")


async def download_full_data_on_startup():
    """Download full station and weather data on startup if needed."""
    if not engine:
        return
    
    logger.info("Checking if full data download is needed...")
    
    # Download airports.csv if it doesn't exist (one-time setup)
    if not engine.data_manager.AIRPORTS_CSV_FILE.exists():
        logger.info("airports.csv not found, downloading from GitHub...")
        await engine.data_manager.download_airports_csv()
    
    # Check if we need to download stations
    if engine.data_manager.should_refresh_stations():
        logger.info("Downloading full station list...")
        try:
            stations = await engine.data_manager.download_full_stations()
            if stations:
                # Enhance station names with airports.csv (matching by ICAO)
                logger.info("Enhancing station names with airports.csv...")
                stations = await engine.data_manager.enhance_station_names_with_airports(stations)
                engine.data_manager.save_stations(stations)
                # Reload station database with new data
                for station_dict in stations:
                    try:
                        from src.stations import Station
                        station = Station(
                            icao=station_dict["icao"],
                            lat=station_dict.get("lat", 0.0),
                            lon=station_dict.get("lon", 0.0),
                            name=station_dict.get("name", ""),
                            country=station_dict.get("country", ""),
                        )
                        engine.station_db.stations[station.icao] = station
                    except Exception as e:
                        logger.warning(f"Error adding station {station_dict.get('icao', 'unknown')}: {e}")
                logger.info(f"Updated station database with {len(stations)} stations")
        except Exception as e:
            logger.error(f"Error downloading stations: {e}", exc_info=True)
    else:
        # Stations are already cached - enhance names using local cache only (no API calls on startup)
        logger.info("Stations are already cached. Enhancing names from local cache...")
        existing_stations = engine.data_manager.load_stations()
        if existing_stations:
            # Load airport data cache if not loaded
            if not engine.data_manager.airport_data_cache:
                engine.data_manager.airport_data_cache = engine.data_manager.load_airport_data()
            
            # Enhance using local cache only
            enhanced = engine.data_manager.enhance_station_names_from_local_cache(existing_stations)
            
            # Enhance with airports.csv (always try, even if airportsdata library not installed)
            enhanced = await engine.data_manager.enhance_station_names_with_airports(enhanced)
            
            if enhanced:
                engine.data_manager.save_stations(enhanced)
                # Reload into station database
                for station_dict in enhanced:
                    try:
                        from src.stations import Station
                        station = Station(
                            icao=station_dict["icao"],
                            lat=station_dict.get("lat", 0.0),
                            lon=station_dict.get("lon", 0.0),
                            name=station_dict.get("name", ""),
                            country=station_dict.get("country", ""),
                        )
                        engine.station_db.stations[station.icao] = station
                    except Exception as e:
                        logger.warning(f"Error updating station {station_dict.get('icao', 'unknown')}: {e}")
                logger.info(f"Enhanced station names from local cache (background task will update missing names later)")
    
    # Check if we need to download weather
    if engine.data_manager.should_refresh_weather():
        logger.info("Downloading full weather data from cache files...")
        try:
            # Download ALL METARs from cache (not just known stations)
            # This gives us worldwide coverage
            metars = await engine.data_manager.download_full_metar()
            if metars:
                engine.data_manager.save_metar(metars, archive=True)
                # Load into memory
                for icao, raw_metar in metars.items():
                    try:
                        from src.metar_parser import parse_metar
                        parsed = parse_metar(raw_metar)
                        engine.current_metars[icao.upper()] = (parsed, time.time())
                    except Exception as e:
                        logger.warning(f"Error parsing downloaded METAR for {icao}: {e}")
                logger.info(f"Loaded {len(metars)} METAR reports into memory")
            else:
                logger.warning("No METAR data downloaded")
            
            # Download ALL TAFs from cache (not just known stations)
            # This gives us worldwide coverage
            tafs = await engine.data_manager.download_full_taf()
            if tafs:
                engine.data_manager.save_taf(tafs, archive=True)
                # Load into memory
                for icao, raw_taf in tafs.items():
                    try:
                        from src.taf_parser import parse_taf
                        parsed = parse_taf(raw_taf)
                        engine.current_tafs[icao.upper()] = (parsed, time.time())
                    except Exception as e:
                        logger.warning(f"Error parsing downloaded TAF for {icao}: {e}")
                logger.info(f"Loaded {len(tafs)} TAF reports into memory")
            else:
                logger.warning("No TAF data downloaded")
        except Exception as e:
            logger.error(f"Error downloading weather: {e}", exc_info=True)
    
    # Cleanup old archives
    engine.data_manager.cleanup_old_archives(days_to_keep=7)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    global update_task, engine, websocket_clients
    
    # Close all WebSocket connections
    if websocket_clients:
        for client in list(websocket_clients):  # Copy list to avoid modification during iteration
            try:
                await client.close()
            except Exception:
                pass
        websocket_clients.clear()
    
    # Cancel update task
    if update_task:
        update_task.cancel()
        try:
            await update_task
        except asyncio.CancelledError:
            pass
    
    # Shutdown engine
    if engine:
        engine.shutdown()
    
    logger.info("FSX Weather Bridge stopped")


async def update_loop():
    """Background update loop."""
    global engine
    
    if not engine:
        return
    
    while True:
        try:
            status = await engine.update()
            
            # Broadcast to WebSocket clients
            if websocket_clients:
                message = json.dumps({
                    "type": "update",
                    "data": status,
                })
                disconnected = []
                for client in websocket_clients:
                    try:
                        await client.send_text(message)
                    except (WebSocketDisconnect, ConnectionResetError, RuntimeError, OSError):
                        # Client disconnected or connection error - remove from list
                        disconnected.append(client)
                    except Exception as e:
                        # Log unexpected errors but still remove client
                        logger.debug(f"WebSocket send error: {e}")
                        disconnected.append(client)
                
                for client in disconnected:
                    try:
                        websocket_clients.remove(client)
                    except ValueError:
                        # Already removed
                        pass
            
            # Sleep based on config (default 1 second for frequent updates)
            sleep_interval = config.web_ui.update_interval_seconds if config and hasattr(config.web_ui, 'update_interval_seconds') else 1.0
            await asyncio.sleep(sleep_interval)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in update loop: {e}")
            await asyncio.sleep(5.0)


@app.get("/")
async def root():
    """Root page - redirect to status."""
    return FileResponse(templates_dir / "status.html") if templates_dir.exists() else {"message": "FSX Weather Bridge API"}


@app.get("/status")
async def status_page():
    """Status page."""
    return FileResponse(templates_dir / "status.html") if templates_dir.exists() else {"message": "Status page"}


@app.get("/map")
async def map_page():
    """Map page."""
    return FileResponse(templates_dir / "map.html") if templates_dir.exists() else {"message": "Map page"}


@app.get("/settings")
async def settings_page():
    """Settings page."""
    return FileResponse(templates_dir / "settings.html") if templates_dir.exists() else {"message": "Settings page"}


@app.get("/logs")
async def logs_page():
    """Logs page."""
    return FileResponse(templates_dir / "logs.html") if templates_dir.exists() else {"message": "Logs page"}


@app.get("/stored-weather")
async def stored_weather_page():
    """Stored weather data page."""
    return FileResponse(templates_dir / "stored_weather.html") if templates_dir.exists() else {"message": "Stored weather page"}


@app.get("/test-weather")
async def test_weather_page():
    """Weather injection test page."""
    return FileResponse(templates_dir / "test_weather.html") if templates_dir.exists() else {"message": "Test weather page"}


@app.get("/manual-weather")
async def manual_weather_page():
    """Manual weather injection page."""
    return FileResponse(templates_dir / "manual_weather.html") if templates_dir.exists() else {"message": "Manual weather page"}


@app.get("/api/status")
async def api_status():
    """Get current status."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    status = engine.get_status()
    aircraft_state = get_aircraft_state_from_bridge(engine.fsuipc_bridge) if engine.fsuipc_bridge else None
    
    return {
        "status": status,
        "aircraft_state": aircraft_state,
        "config": config.dict() if config else None,
    }


@app.get("/api/settings")
async def get_settings():
    """Get current settings."""
    if not config:
        raise HTTPException(status_code=503, detail="Config not loaded")
    
    return config.dict()


@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate):
    """Update settings."""
    global config, engine
    
    if not config:
        raise HTTPException(status_code=503, detail="Config not loaded")
    
    # Update config
    if settings.weather_source:
        config.weather_source = WeatherSourceConfig(**settings.weather_source)
    if settings.weather_combining:
        config.weather_combining = WeatherCombiningConfig(**settings.weather_combining)
    if settings.smoothing:
        config.smoothing = SmoothingConfig(**settings.smoothing)
    if settings.station_selection:
        config.station_selection = StationSelectionConfig(**settings.station_selection)
    if settings.manual_weather:
        config.manual_weather = ManualWeatherConfig(**settings.manual_weather)
    if settings.fsuipc:
        config.fsuipc = FSUIPCConfig(**settings.fsuipc)
    if settings.web_ui:
        config.web_ui = WebUIConfig(**settings.web_ui)
    
    # Save config
    config.save()
    
    # Reinitialize engine if needed
    if engine:
        engine.shutdown()
    engine = WeatherEngine(config)
    
    return {"success": True}


@app.get("/api/stations")
async def get_stations():
    """Get station database."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    return engine.station_db.to_geojson()


@app.get("/api/weather/availability")
async def get_weather_availability():
    """Get weather availability for all loaded stations (returns dict of icao -> {has_metar, has_taf}). Cached for 30 seconds."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # Check cache
    cached = api_cache.get("weather_availability")
    if cached is not None:
        logger.debug("Returning cached weather availability data")
        return JSONResponse(content=cached, headers={"Cache-Control": "public, max-age=30"})
    
    # Generate fresh data
    availability = {}
    
    # Check all stations in database
    for icao, station in engine.station_db.stations.items():
        has_metar = icao.upper() in engine.current_metars
        has_taf = icao.upper() in engine.current_tafs
        availability[icao.upper()] = {
            "has_metar": has_metar,
            "has_taf": has_taf,
            "has_weather": has_metar or has_taf,
        }
    
    # Cache for 30 seconds (weather data changes more frequently)
    api_cache.set("weather_availability", availability, ttl=30.0)
    
    return JSONResponse(content=availability, headers={"Cache-Control": "public, max-age=30"})


@app.get("/api/weather/stored")
async def get_stored_weather():
    """Get list of all ICAO codes with stored weather data. Cached for 30 seconds."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # Check cache
    cached = api_cache.get("weather_stored")
    if cached is not None:
        logger.debug("Returning cached stored weather data")
        return JSONResponse(content=cached, headers={"Cache-Control": "public, max-age=30"})
    
    # Generate fresh data
    stored_icaos = set()
    
    # Get all ICAOs with METAR
    stored_icaos.update(engine.current_metars.keys())
    logger.debug(f"Stored weather check: METAR keys={len(engine.current_metars)}, TAF keys={len(engine.current_tafs)}")
    
    # Get all ICAOs with TAF
    stored_icaos.update(engine.current_tafs.keys())
    
    # Build detailed list
    weather_list = []
    for icao in sorted(stored_icaos):
        metar_info = None
        taf_info = None
        
        if icao in engine.current_metars:
            metar, timestamp = engine.current_metars[icao]
            metar_info = {
                "age_seconds": time.time() - timestamp,
                "has_data": True,
                "raw": metar.raw if hasattr(metar, 'raw') else str(metar)[:100],
            }
        
        if icao in engine.current_tafs:
            taf, timestamp = engine.current_tafs[icao]
            taf_info = {
                "age_seconds": time.time() - timestamp,
                "has_data": True,
                "raw": taf.raw if hasattr(taf, 'raw') else str(taf)[:100],
            }
        
        # Get station info if available
        station = engine.station_db.get_station(icao)
        station_name = station.name if station else "Not defined"
        country = station.country if station else "Not defined"
        
        weather_list.append({
            "icao": icao,
            "station_name": station_name,
            "country": country,
            "metar": metar_info,
            "taf": taf_info,
        })
    
    result = {
        "count": len(weather_list),
        "weather_data": weather_list,
    }
    
    # Cache for 30 seconds (weather data changes more frequently)
    api_cache.set("weather_stored", result, ttl=30.0)
    
    logger.debug(f"Returning {len(weather_list)} stored weather entries")
    
    return JSONResponse(content=result, headers={"Cache-Control": "public, max-age=30"})


@app.get("/api/weather/{icao}")
async def get_weather_for_icao(icao: str):
    """Get weather data for a specific ICAO code."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    result = engine.get_weather_for_icao(icao)
    
    # Always return result, even if no weather data (will have None values)
    # Check if we have any data at all
    if result and (result.get("metar") or result.get("taf") or result.get("station")):
        return result
    else:
        # No data found - return 404 with helpful message
        raise HTTPException(
            status_code=404, 
            detail=f"No weather data found for {icao.upper()}. Use POST /api/weather/fetch/{icao.upper()} to fetch it."
        )


@app.post("/api/weather/fetch/{icao}")
async def fetch_weather_for_icao(icao: str):
    """Force fetch weather for a specific ICAO code."""
    try:
        if not engine:
            raise HTTPException(status_code=503, detail="Engine not initialized")
        
        if not engine.weather_source:
            raise HTTPException(status_code=503, detail="Weather source not enabled")
        
        icao_upper = icao.upper()
        logger.info(f"Force fetching weather for {icao_upper}")
        
        # Fetch METAR and TAF
        metars = await engine.weather_source.fetch_metar([icao_upper])
        tafs = await engine.weather_source.fetch_taf([icao_upper])
        
        logger.info(f"Fetched: METAR={len(metars)} (keys: {list(metars.keys())}), TAF={len(tafs)} (keys: {list(tafs.keys())})")
        
        # Parse and store
        from src.metar_parser import parse_metar
        from src.taf_parser import parse_taf
        
        stored_metar = False
        stored_taf = False
        
        # Store METAR - normalize ICAO to uppercase
        for icao_code, raw_metar in metars.items():
            try:
                icao_normalized = icao_code.upper().strip()
                parsed = parse_metar(raw_metar)
                engine.current_metars[icao_normalized] = (parsed, time.time())
                stored_metar = True
                logger.info(f"Stored METAR for {icao_normalized} in memory (total stored: {len(engine.current_metars)}, keys: {list(engine.current_metars.keys())})")
            except Exception as e:
                logger.error(f"Error parsing METAR for {icao_code}: {e}", exc_info=True)
        
        # Store TAF - normalize ICAO to uppercase
        for icao_code, raw_taf in tafs.items():
            try:
                icao_normalized = icao_code.upper().strip()
                parsed = parse_taf(raw_taf)
                engine.current_tafs[icao_normalized] = (parsed, time.time())
                stored_taf = True
                logger.info(f"Stored TAF for {icao_normalized} in memory (total stored: {len(engine.current_tafs)}, keys: {list(engine.current_tafs.keys())})")
            except Exception as e:
                logger.error(f"Error parsing TAF for {icao_code}: {e}", exc_info=True)
        
        # Verify storage
        result_data = engine.get_weather_for_icao(icao_upper)
        logger.info(f"Verification: METAR stored={icao_upper in engine.current_metars}, TAF stored={icao_upper in engine.current_tafs}")
        
        if not stored_metar and not stored_taf:
            return {
                "success": False,
                "message": f"No weather data received for {icao_upper}",
                "data": result_data,
                "stored_metar": False,
                "stored_taf": False,
            }
        
        return {
            "success": True,
            "message": f"Weather fetched for {icao_upper}",
            "data": result_data,
            "stored_metar": icao_upper in engine.current_metars,
            "stored_taf": icao_upper in engine.current_tafs,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching weather for {icao}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching weather: {str(e)}")


@app.post("/api/manual")
async def set_manual_weather(request: ManualWeatherRequest):
    """Set manual weather mode."""
    global config
    
    if not config:
        raise HTTPException(status_code=503, detail="Config not loaded")
    
    config.manual_weather.enabled = True
    config.manual_weather.mode = request.mode
    config.manual_weather.icao = request.icao
    config.manual_weather.raw_metar = request.raw_metar
    config.manual_weather.raw_taf = request.raw_taf
    config.manual_weather.freeze = request.freeze
    
    config.save()
    
    return {"success": True}


@app.post("/api/trigger-update")
async def trigger_update():
    """Manually trigger full weather update (fetch, process, inject)."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    try:
        logger.info("Manual trigger update requested")
        status = await engine.update()
        
        # Get aircraft state for response
        aircraft_state = get_aircraft_state_from_bridge(engine.fsuipc_bridge) if engine.fsuipc_bridge else None
        
        return {
            "success": True,
            "message": "Update completed",
            "status": status,
            "aircraft_state": aircraft_state,
        }
    except Exception as e:
        logger.error(f"Error in trigger update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error during update: {str(e)}")


@app.post("/api/data/refresh-stations")
async def refresh_stations():
    """Force refresh station list from AviationWeather.gov and invalidate cache."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    try:
        logger.info("Force refreshing station list...")
        stations = await engine.data_manager.download_full_stations()
        if stations:
            engine.data_manager.save_stations(stations)
            # Reload station database with new data
            for station_dict in stations:
                try:
                    from src.stations import Station
                    station = Station(
                        icao=station_dict["icao"],
                        lat=station_dict.get("lat", 0.0),
                        lon=station_dict.get("lon", 0.0),
                        name=station_dict.get("name", ""),
                        country=station_dict.get("country", ""),
                    )
                    engine.station_db.stations[station.icao] = station
                except Exception as e:
                    logger.warning(f"Error adding station {station_dict.get('icao', 'unknown')}: {e}")
            logger.info(f"Updated station database with {len(stations)} stations")
            
            # Invalidate cache
            api_cache.invalidate("stations")
            api_cache.invalidate("weather_availability")  # Also invalidate availability since stations changed
            
            return {
                "success": True,
                "message": f"Downloaded and loaded {len(stations)} stations",
                "count": len(stations),
            }
        else:
            return {
                "success": False,
                "message": "No stations downloaded",
                "count": 0,
            }
    except Exception as e:
        logger.error(f"Error refreshing stations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error refreshing stations: {str(e)}")


@app.post("/api/data/refresh-weather")
async def refresh_weather():
    """Force refresh weather data (METAR and TAF) from AviationWeather.gov cache and invalidate cache."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    try:
        logger.info("Force refreshing weather data...")
        # Download METARs
        metars = await engine.data_manager.download_full_metar()
        metars_count = len(metars)
        if metars:
            engine.data_manager.save_metar(metars, archive=True)
            # Load into memory
            for icao, raw_metar in metars.items():
                try:
                    from src.metar_parser import parse_metar
                    parsed = parse_metar(raw_metar)
                    engine.current_metars[icao.upper()] = (parsed, time.time())
                except Exception as e:
                    logger.warning(f"Error parsing downloaded METAR for {icao}: {e}")
            logger.info(f"Loaded {metars_count} METAR reports into memory")
        
        # Download TAFs
        tafs = await engine.data_manager.download_full_taf()
        tafs_count = len(tafs)
        if tafs:
            engine.data_manager.save_taf(tafs, archive=True)
            # Load into memory
            for icao, raw_taf in tafs.items():
                try:
                    from src.taf_parser import parse_taf
                    parsed = parse_taf(raw_taf)
                    engine.current_tafs[icao.upper()] = (parsed, time.time())
                except Exception as e:
                    logger.warning(f"Error parsing downloaded TAF for {icao}: {e}")
            logger.info(f"Loaded {tafs_count} TAF reports into memory")
        
        # Invalidate weather-related cache
        api_cache.invalidate("weather_availability")
        api_cache.invalidate("weather_stored")
        
        return {
            "success": True,
            "message": f"Downloaded {metars_count} METARs and {tafs_count} TAFs",
            "metars_count": metars_count,
            "tafs_count": tafs_count,
        }
    except Exception as e:
        logger.error(f"Error refreshing weather: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error refreshing weather: {str(e)}")


@app.get("/api/data/statistics")
async def get_data_statistics():
    """Get data statistics (stations, METARs, TAFs counts and file ages)."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    status = engine.get_status()
    return status.get("data_statistics", {})


@app.post("/api/data/enhance-station-names")
async def enhance_station_names():
    """Enhance existing station names using AviationWeather.gov airport database."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    try:
        logger.info("Enhancing station names with AviationWeather.gov airport database...")
        
        # Get all current stations
        stations_list = []
        for icao, station in engine.station_db.stations.items():
            stations_list.append({
                "icao": station.icao,
                "lat": station.lat,
                "lon": station.lon,
                "name": station.name,
                "country": station.country,
            })
        
        # Enhance names - use airportsdata first (fast local lookup, 28,000+ airports), then AviationWeather.gov as fallback
        if hasattr(engine.data_manager, 'enhance_station_names_with_airports'):
            try:
                logger.info("Enhancing station names using airportsdata library (fast local lookup, 28,000+ airports)...")
                enhanced_stations = await engine.data_manager.enhance_station_names_with_airports(stations_list)
                
                # Check if any stations still need enhancement
                stations_needing_enhancement = [
                    s for s in enhanced_stations 
                    if not s.get("name") or s.get("name", "").startswith("Station ") or len(s.get("name", "")) < 5
                ]
                if stations_needing_enhancement:
                    logger.info(f"Enhancing {len(stations_needing_enhancement)} remaining stations from AviationWeather.gov...")
                    enhanced_stations = await engine.data_manager.enhance_station_names_from_aviationweather(enhanced_stations)
            except Exception as e:
                logger.warning(f"Error with airportsdata enhancement, falling back to AviationWeather.gov: {e}")
                enhanced_stations = await engine.data_manager.enhance_station_names_from_aviationweather(stations_list)
        else:
            # Fallback to AviationWeather.gov if airportsdata not available
            logger.info("airportsdata not available, using AviationWeather.gov API...")
            enhanced_stations = await engine.data_manager.enhance_station_names_from_aviationweather(stations_list)
        
        # Update station database
        enhanced_count = 0
        for station_dict in enhanced_stations:
            icao = station_dict["icao"]
            if icao in engine.station_db.stations:
                old_name = engine.station_db.stations[icao].name
                new_name = station_dict.get("name", "")
                if new_name != old_name and new_name:
                    engine.station_db.stations[icao].name = new_name
                    enhanced_count += 1
                
                # Update country if improved
                if not engine.station_db.stations[icao].country or engine.station_db.stations[icao].country == "Unknown":
                    new_country = station_dict.get("country", "")
                    if new_country and new_country != "Unknown":
                        engine.station_db.stations[icao].country = new_country
        
        # Save enhanced stations to file
        engine.data_manager.save_stations(enhanced_stations)
        
        return {
            "success": True,
            "message": f"Enhanced {enhanced_count} station names",
            "enhanced_count": enhanced_count,
            "total_stations": len(enhanced_stations),
        }
    except Exception as e:
        logger.error(f"Error enhancing station names: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error enhancing station names: {str(e)}")


@app.post("/api/force-weather-download")
async def force_weather_download():
    """Force weather download for current stations (bypasses rate limiting) and invalidate cache."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    logger.info("Force weather download requested (bypassing rate limits)")
    
    # Get ICAO codes
    icaos = []
    if not engine.config.manual_weather.enabled or engine.config.manual_weather.mode != "report":
        for station, _ in engine.current_stations:
            icaos.append(station.icao)
    
    if not icaos:
        return {"success": False, "message": "No stations selected"}
    
    current_time = time.time()
    metars_count = 0
    tafs_count = 0
    
    # Force fetch METAR (bypass rate limiting)
    if engine.config.weather_source.enabled and engine.weather_source:
        metars = await engine.weather_source.fetch_metar(icaos)
        from src.metar_parser import parse_metar
        metars_dict = {}
        for icao, raw_metar in metars.items():
            try:
                parsed = parse_metar(raw_metar)
                engine.current_metars[icao] = (parsed, current_time)
                engine.last_metar_fetch[icao] = current_time
                metars_dict[icao] = raw_metar
                metars_count += 1
            except Exception as e:
                logger.warning(f"Error parsing METAR for {icao}: {e}")
        
        if metars_dict:
            existing_metars = engine.data_manager.load_metar()
            existing_metars.update(metars_dict)
            engine.data_manager.save_metar(existing_metars, archive=True)
    
    # Force fetch TAF (bypass rate limiting)
    if engine.config.weather_source.enabled and engine.weather_source:
        tafs = await engine.weather_source.fetch_taf(icaos)
        from src.taf_parser import parse_taf
        tafs_dict = {}
        for icao, raw_taf in tafs.items():
            try:
                parsed = parse_taf(raw_taf)
                engine.current_tafs[icao] = (parsed, current_time)
                engine.last_taf_fetch[icao] = current_time
                tafs_dict[icao] = raw_taf
                tafs_count += 1
            except Exception as e:
                logger.warning(f"Error parsing TAF for {icao}: {e}")
        
        if tafs_dict:
            existing_tafs = engine.data_manager.load_taf()
            existing_tafs.update(tafs_dict)
            engine.data_manager.save_taf(existing_tafs, archive=True)
    
    # Invalidate weather-related cache
    api_cache.invalidate("weather_availability")
    api_cache.invalidate("weather_stored")
    
    return {
        "success": True,
        "message": f"Weather download completed: {metars_count} METARs, {tafs_count} TAFs",
        "metars_count": metars_count,
        "tafs_count": tafs_count,
    }


@app.post("/api/weather/test-inject")
async def test_weather_injection(
    wind_dir: int = 0,
    wind_speed_kt: float = 30.0,
    cloud_base_ft: int = 0,
    cloud_top_ft: int = 10000,
    cloud_coverage: str = "OVC",
    visibility_nm: float = 10.0,
    temperature_c: float = 15.0,
    qnh_hpa: float = 1013.25,
    station_icao: Optional[str] = None,
):
    """
    Test weather injection with custom parameters.
    
    Args:
        wind_dir: Wind direction in degrees (0-360)
        wind_speed_kt: Wind speed in knots
        cloud_base_ft: Cloud base altitude in feet
        cloud_top_ft: Cloud top altitude in feet
        cloud_coverage: Cloud coverage (SKC, FEW, SCT, BKN, OVC)
        visibility_nm: Visibility in nautical miles
        temperature_c: Temperature in Celsius
        qnh_hpa: QNH pressure in hPa
        station_icao: Optional station ICAO code for station-specific injection
    """
    try:
        from src.weather_smoother import WeatherState
        
        # Create test weather state
        test_weather = WeatherState()
        test_weather.wind_dir_deg = float(wind_dir % 360)
        test_weather.wind_speed_kt = float(wind_speed_kt)
        test_weather.wind_gust_kt = None
        test_weather.visibility_nm = float(visibility_nm)
        test_weather.temperature_c = float(temperature_c)
        test_weather.dewpoint_c = float(temperature_c) - 5.0  # Simple dewpoint calculation
        test_weather.qnh_hpa = float(qnh_hpa)
        test_weather.weather_tokens = []
        
        # Create cloud layers from base to top
        test_weather.clouds = []
        if cloud_coverage != "SKC" and cloud_base_ft < cloud_top_ft:
            # Create a single overcast layer from base to top
            test_weather.clouds.append({
                "coverage": cloud_coverage,
                "base_ft": float(cloud_base_ft),
                "top_ft": float(cloud_top_ft),
            })
        
        # Get aircraft position if available
        aircraft_lat = None
        aircraft_lon = None
        if engine.fsuipc_bridge and engine.fsuipc_bridge.is_connected():
            aircraft_state = engine.fsuipc_bridge.get_aircraft_state()
            if aircraft_state:
                aircraft_lat = aircraft_state.lat
                aircraft_lon = aircraft_state.lon
        
        # Inject test weather
        logger.info(f"Test weather injection: Wind {wind_dir}°/{wind_speed_kt}kt, "
                   f"Clouds {cloud_coverage} {cloud_base_ft}-{cloud_top_ft}ft, "
                   f"Vis {visibility_nm}nm, QNH {qnh_hpa}hPa")
        
        success = engine.injector.inject_weather(
            test_weather,
            aircraft_lat,
            aircraft_lon,
            station_icao=station_icao
        )
        
        if success:
            return JSONResponse({
                "success": True,
                "message": "Test weather injected successfully",
                "weather": test_weather.to_dict(),
            })
        else:
            return JSONResponse({
                "success": False,
                "message": "Test weather injection failed",
                "weather": test_weather.to_dict(),
            }, status_code=500)
            
    except Exception as e:
        logger.error(f"Error in test weather injection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/weather/test-inject")
async def test_weather_injection(
    wind_dir: int = 0,
    wind_speed_kt: float = 30.0,
    cloud_base_ft: int = 0,
    cloud_top_ft: int = 10000,
    cloud_coverage: str = "OVC",
    visibility_nm: float = 10.0,
    temperature_c: float = 15.0,
    qnh_hpa: float = 1013.25,
    station_icao: Optional[str] = None,
):
    """
    Test weather injection with custom parameters.
    
    Default test: Overcast sky from 0 to 10000ft, 30 knots wind.
    
    Args:
        wind_dir: Wind direction in degrees (0-360)
        wind_speed_kt: Wind speed in knots
        cloud_base_ft: Cloud base altitude in feet
        cloud_top_ft: Cloud top altitude in feet (for reference, FSX uses base only)
        cloud_coverage: Cloud coverage (SKC, FEW, SCT, BKN, OVC)
        visibility_nm: Visibility in nautical miles
        temperature_c: Temperature in Celsius
        qnh_hpa: QNH pressure in hPa
        station_icao: Optional station ICAO code for station-specific injection
    """
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    try:
        from src.weather_smoother import WeatherState
        
        # Create test weather state
        test_weather = WeatherState()
        test_weather.wind_dir_deg = float(wind_dir % 360)
        test_weather.wind_speed_kt = float(wind_speed_kt)
        test_weather.wind_gust_kt = None
        test_weather.visibility_nm = float(visibility_nm)
        test_weather.temperature_c = float(temperature_c)
        test_weather.dewpoint_c = float(temperature_c) - 5.0  # Simple dewpoint calculation
        test_weather.qnh_hpa = float(qnh_hpa)
        test_weather.weather_tokens = []
        
        # Create cloud layer (FSX uses base altitude, not top)
        test_weather.clouds = []
        if cloud_coverage != "SKC":
            # Create a single cloud layer at the specified base
            test_weather.clouds.append({
                "coverage": cloud_coverage,
                "base_ft": float(cloud_base_ft),
            })
        
        # Get aircraft position if available
        aircraft_lat = None
        aircraft_lon = None
        if engine.fsuipc_bridge and engine.fsuipc_bridge.is_connected():
            aircraft_state = engine.fsuipc_bridge.get_aircraft_state()
            if aircraft_state:
                aircraft_lat = aircraft_state.lat
                aircraft_lon = aircraft_state.lon
        
        # Inject test weather
        logger.info(f"Test weather injection: Wind {wind_dir}°/{wind_speed_kt}kt, "
                   f"Clouds {cloud_coverage} {cloud_base_ft}ft, "
                   f"Vis {visibility_nm}nm, QNH {qnh_hpa}hPa")
        
        success = engine.injector.inject_weather(
            test_weather,
            aircraft_lat,
            aircraft_lon,
            station_icao=station_icao
        )
        
        if success:
            return JSONResponse({
                "success": True,
                "message": "Test weather injected successfully",
                "weather": test_weather.to_dict(),
            })
        else:
            return JSONResponse({
                "success": False,
                "message": "Test weather injection failed",
                "weather": test_weather.to_dict(),
            }, status_code=500)
            
    except Exception as e:
        logger.error(f"Error in test weather injection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/weather/inject-raw")
async def inject_raw_metar_endpoint(request: InjectRawMetarRequest):
    """Inject a raw METAR string (e.g. GLOB 171844Z 09050KT 9999 SKC 15/10 Q1013 or SBGR METAR 171844Z 09050KT 1600 FG OVC005 15/10 Q1013)."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    if not hasattr(engine.injector, "inject_raw_metar"):
        raise HTTPException(status_code=501, detail="Raw METAR injection is only available with SimConnect injector")
    success = engine.injector.inject_raw_metar(request.metar)
    return {"success": success, "message": "Raw METAR injected" if success else "Raw METAR injection failed"}


@app.post("/api/force-weather-injection")
async def force_weather_injection():
    """Force weather injection."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    logger.info("Force weather injection requested")
    weather = await engine._process_weather()
    
    if weather:
        smoothed = engine.weather_smoother.smooth(weather)
        success = engine.injector.inject_weather(smoothed)
        return {"success": success, "message": "Weather injection triggered" if success else "Weather injection failed"}
    else:
        return {"success": False, "message": "No weather data available to inject"}


@app.post("/api/fsuipc/connect")
async def fsuipc_connect():
    """Force FSUIPC connection."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    if not engine.fsuipc_bridge:
        return {"success": False, "message": "FSUIPC bridge not initialized"}
    
    logger.info("Force FSUIPC connect requested")
    success = engine.fsuipc_bridge.connect()
    
    return {"success": success, "message": "Connected" if success else "Connection failed"}


@app.post("/api/fsuipc/disconnect")
async def fsuipc_disconnect():
    """Disconnect FSUIPC."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    if not engine.fsuipc_bridge:
        return {"success": False, "message": "FSUIPC bridge not initialized"}
    
    logger.info("FSUIPC disconnect requested")
    engine.fsuipc_bridge.disconnect()
    
    return {"success": True, "message": "Disconnected"}


@app.post("/api/fsuipc/reconnect")
async def fsuipc_reconnect():
    """Force FSUIPC reconnection."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    if not engine.fsuipc_bridge:
        return {"success": False, "message": "FSUIPC bridge not initialized"}
    
    logger.info("Force FSUIPC reconnect requested")
    engine.fsuipc_bridge.disconnect()
    await asyncio.sleep(0.5)
    success = engine.fsuipc_bridge.connect()
    
    return {"success": success, "message": "Reconnected" if success else "Reconnection failed"}


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    """Get application logs."""
    return {"logs": log_buffer[-limit:]}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for live updates."""
    await websocket.accept()
    websocket_clients.append(websocket)
    
    try:
        while True:
            # Keep connection alive and handle incoming messages
            try:
                data = await websocket.receive_text()
                # Echo back or handle commands
                await websocket.send_text(json.dumps({"type": "pong", "data": data}))
            except WebSocketDisconnect:
                break
            except (ConnectionResetError, RuntimeError, OSError):
                # Connection lost
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
    finally:
        # Remove from clients list
        try:
            websocket_clients.remove(websocket)
        except ValueError:
            # Already removed
            pass


