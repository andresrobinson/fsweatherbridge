# FSX Weather Bridge - Architecture Documentation

## System Architecture Overview

FSX Weather Bridge is built as a multi-threaded Python application with a web-based user interface. The architecture follows a modular design with clear separation of concerns.

---

## Component Architecture

### 1. Main Entry Point (`src/main.py`)

**Responsibilities**:
- Application initialization
- Logging configuration
- Thread management (server thread, tray icon thread)
- Signal handling (graceful shutdown)
- System tray icon management

**Key Functions**:
- `main()`: Entry point, sets up logging, starts server thread, manages tray icon
- `run_server()`: Runs FastAPI/Uvicorn server in background thread
- `create_tray_icon()`: Creates system tray icon with menu
- `exit_app()`: Graceful shutdown handler

**Threading Model**:
- **Main Thread**: Manages application lifecycle, waits for shutdown
- **Server Thread**: Runs FastAPI/Uvicorn (non-daemon, can be joined)
- **Tray Icon Thread**: Runs pystray icon (daemon, exits with main)

### 2. Core Engine (`src/app_core.py`)

**WeatherEngine Class**: Central orchestrator for all weather processing

**Responsibilities**:
- Coordinate data fetching, parsing, combining, smoothing, and injection
- Manage station selection based on aircraft position
- Handle update cycles
- Persist and load data

**Key Methods**:
- `__init__()`: Initialize all components
- `_initialize()`: Set up weather source, FSUIPC bridge, injector
- `_load_persisted_data()`: Load cached stations and weather from files
- `update()`: Main update cycle (async)
- `_select_stations()`: Select nearby weather stations
- `_fetch_weather()`: Fetch METAR/TAF for selected stations
- `_process_weather()`: Combine, smooth, and inject weather

**State Management**:
- `current_stations`: List of selected stations with distances
- `current_metars`: Dictionary of parsed METARs by ICAO
- `current_tafs`: Dictionary of parsed TAFs by ICAO
- `last_injected_weather`: Last successfully injected weather state
- `last_injection_time`: Timestamp of last injection

### 3. Data Management (`src/data_manager.py`)

**DataManager Class**: Handles all data persistence and fetching

**Responsibilities**:
- Download stations, METAR, and TAF data from AviationWeather.gov
- Cache data locally (JSON files)
- Archive historical weather data
- Enhance station names from airport databases

**Key Methods**:
- `download_full_stations()`: Download complete station list
- `download_metar()`: Download METAR data (individual or cache file)
- `download_taf()`: Download TAF data
- `load_stations()`: Load stations from cache file
- `load_metar()`: Load METAR from cache file
- `load_taf()`: Load TAF from cache file
- `save_stations()`: Save stations to cache file
- `save_metar()`: Save METAR to cache file
- `save_taf()`: Save TAF to cache file
- `enhance_station_names()`: Add airport names to stations

**Data Files**:
- `data/stations_full.json`: Station database
- `data/metar_latest.json`: Latest METAR data
- `data/taf_latest.json`: Latest TAF data
- `data/metar_archive/`: Historical METAR archives
- `data/taf_archive/`: Historical TAF archives
- `data/airports.csv`: Local airport database (from airportsdata)

### 4. Weather Sources (`src/weather_sources.py`)

**WeatherSource Abstract Class**: Base class for weather data sources

**AviationWeatherSource Class**: Fetches data from AviationWeather.gov API

**Responsibilities**:
- Fetch METAR/TAF data via HTTP
- Cache responses
- Handle API errors and retries
- Parse API responses

**Key Methods**:
- `fetch_metar()`: Fetch METAR for specific stations
- `fetch_taf()`: Fetch TAF for specific stations
- `_fetch_with_cache()`: HTTP fetch with caching

### 5. Parsing (`src/metar_parser.py`, `src/taf_parser.py`)

**METAR Parser**:
- Regex-based parsing (pragmatic, not full ICAO-compliant)
- Extracts: wind, visibility, temperature, pressure, clouds, weather codes
- Returns `ParsedMETAR` object

**TAF Parser**:
- Parses forecast groups (FM, TEMPO, PROB)
- Extracts prevailing and group-specific conditions
- Returns `ParsedTAF` object

### 6. Weather Combining (`src/weather_combiner.py`)

**combine_weather() Function**: Combines METAR and TAF according to mode

**Modes**:
- `metar_only`: Use METAR only
- `metar_taf_fallback`: METAR if fresh, TAF if stale
- `metar_taf_assist`: METAR for current, TAF for forecast

**Returns**: `CombinedWeather` object with all weather parameters

### 7. Weather Smoothing (`src/weather_smoother.py`)

**WeatherSmoother Class**: Implements gradual weather transitions

**Key Features**:
- Step-limited or time-based transitions
- Big change detection (faster transitions)
- Freeze logic (no changes during approach)
- Per-parameter smoothing limits

**Key Methods**:
- `smooth()`: Main smoothing function
- `_smooth_wind_dir()`: Wind direction with wraparound handling
- `_smooth_value()`: Generic numeric smoothing
- `_smooth_clouds()`: Cloud layer smoothing
- `_is_big_change()`: Detect significant weather changes

**State**:
- `current_state`: Last injected weather state
- `frozen`: Whether weather is frozen (during approach)

### 8. Weather Injection (`src/weather_injector.py`)

**WeatherInjector Abstract Class**: Base class for injectors

**FSUIPCWeatherInjector Class**: Injects via FSUIPC offset 0xB000

**DEVInjector Class**: Development injector (logs only, no actual injection)

**Key Methods**:
- `inject_weather()`: Main injection method
- `_build_metar_string()`: Convert weather state to METAR string
- `_inject_station_weather()`: Inject weather for specific station
- `_inject_global_weather()`: Inject global weather

### 9. FSUIPC Bridge (`src/fsuipc_bridge.py`)

**FSUIPCBridge Class**: Manages FSUIPC connection and reads aircraft state

**Responsibilities**:
- Connect to FSUIPC4
- Read aircraft position and state
- Handle reconnection
- Provide aircraft state to other components

**Key Methods**:
- `connect()`: Establish FSUIPC connection
- `disconnect()`: Close connection
- `is_connected()`: Check connection status
- `get_aircraft_state()`: Read current aircraft state
- `_read_position()`: Read lat/lon/alt from FSUIPC
- `_read_motion()`: Read speed/heading from FSUIPC

**AircraftState Class**: Data structure for aircraft state

### 10. Station Database (`src/stations.py`)

**StationDatabase Class**: Manages weather station database

**Station Class**: Represents a single weather station

**Key Methods**:
- `find_nearby()`: Find stations within radius of position
- `get()`: Get station by ICAO code
- `add()`: Add station to database

### 11. Web Application (`src/web_app.py`)

**FastAPI Application**: REST API and WebSocket server

**Endpoints**:
- `GET /`: Status page (HTML)
- `GET /map`: Map page (HTML)
- `GET /settings`: Settings page (HTML)
- `GET /logs`: Logs page (HTML)
- `GET /manual`: Manual weather page (HTML)
- `GET /stored`: Stored weather page (HTML)
- `GET /api/status`: Status JSON
- `GET /api/stations`: Stations JSON
- `GET /api/weather`: Weather data JSON
- `GET /api/config`: Configuration JSON
- `POST /api/config`: Update configuration
- `POST /api/manual-weather`: Set manual weather
- `POST /api/clear-manual-weather`: Clear manual weather
- `GET /api/logs`: Log entries JSON
- `WebSocket /ws`: Real-time updates

**WebSocket Protocol**:
- Client connects to `/ws`
- Server sends updates every `update_interval_seconds`
- Updates include: status, aircraft state, stations, weather

### 12. Configuration (`src/config.py`)

**Configuration Classes**: Pydantic models for type-safe configuration

**Classes**:
- `WeatherSourceConfig`: Weather source settings
- `WeatherCombiningConfig`: METAR/TAF combining mode
- `SmoothingConfig`: Smoothing parameters
- `StationSelectionConfig`: Station selection parameters
- `ManualWeatherConfig`: Manual weather settings
- `FSUIPCConfig`: FSUIPC connection settings
- `WebUIConfig`: Web UI settings
- `AppConfig`: Main configuration (contains all sub-configs)

**Persistence**:
- Saved to: `%USERPROFILE%\.fsweatherbridge\config.json`
- Loaded on startup
- Can be updated via web UI or file edit

---

## Data Flow

### Update Cycle

```
1. WeatherEngine.update() called (every ~1-2 seconds)
   │
   ├─> Get aircraft position from FSUIPCBridge
   │
   ├─> Select nearby stations (StationDatabase.find_nearby())
   │
   ├─> Fetch METAR/TAF for selected stations (AviationWeatherSource)
   │
   ├─> Parse METAR/TAF (METARParser, TAFParser)
   │
   ├─> Combine METAR/TAF (WeatherCombiner.combine_weather())
   │
   ├─> Smooth weather (WeatherSmoother.smooth())
   │
   ├─> Inject weather (WeatherInjector.inject_weather())
   │
   └─> Update web UI via WebSocket
```

### Weather Injection Flow

```
1. WeatherInjector.inject_weather() called with smoothed weather
   │
   ├─> Build METAR string from weather state
   │
   ├─> Determine injection method (station-based or global)
   │
   ├─> Write METAR string to FSUIPC offset 0xB000
   │
   └─> FSUIPC forwards to SimConnect → FSX applies weather
```

### Web UI Update Flow

```
1. Client connects to WebSocket /ws
   │
   ├─> Server sends initial status
   │
   ├─> Every update_interval_seconds:
   │   │
   │   ├─> Get current status from WeatherEngine
   │   │
   │   ├─> Get aircraft state from FSUIPCBridge
   │   │
   │   ├─> Get selected stations
   │   │
   │   ├─> Get current weather
   │   │
   │   └─> Send update to all connected clients
   │
   └─> Client updates UI (map, status, etc.)
```

---

## Threading Model

### Threads

1. **Main Thread**
   - Initializes application
   - Starts server thread
   - Starts tray icon thread
   - Waits for shutdown event
   - Handles graceful shutdown

2. **Server Thread** (UvicornServerThread)
   - Runs FastAPI/Uvicorn server
   - Handles HTTP requests and WebSocket connections
   - Non-daemon (can be joined on shutdown)

3. **Tray Icon Thread**
   - Runs pystray icon
   - Handles menu clicks
   - Daemon thread (exits with main)

### Thread Safety

- **WeatherEngine**: Single instance, accessed from server thread (FastAPI is single-threaded for request handling, but async)
- **FSUIPCBridge**: Thread-safe connection (FSUIPC library handles locking)
- **Configuration**: Read/write protected (Pydantic models are thread-safe for reads, writes should be serialized)
- **Logging**: Thread-safe (Python logging module)

---

## Error Handling

### FSUIPC Connection Errors

- **Initialization Failure**: Falls back to DEV mode (simulated aircraft data)
- **Connection Lost**: Auto-reconnect with configurable interval
- **Read Errors**: Logged, retry on next cycle

### Weather Fetching Errors

- **API Errors**: Logged, use cached data if available
- **Network Errors**: Retry with exponential backoff
- **Parse Errors**: Logged, skip invalid data

### Injection Errors

- **FSUIPC Write Errors**: Logged, retry on next cycle
- **Invalid METAR**: Validation before injection

---

## Performance Considerations

### Caching

- **Stations**: Cached for 24 hours
- **METAR/TAF**: Cached for 1 hour
- **API Responses**: Cached per `cache_seconds` setting

### Update Frequency

- **Weather Updates**: Every 60 seconds (METAR), 600 seconds (TAF)
- **Injection**: Every 1-2 seconds (only if weather changed)
- **Web UI Updates**: Every 1 second (configurable)

### Memory Management

- **Log Buffer**: Limited to 1000 entries (web UI)
- **Station Database**: Loaded once, kept in memory
- **Weather Cache**: Limited by file size, archived periodically

---

## Extension Points

### Adding New Weather Sources

1. Create class inheriting from `WeatherSource`
2. Implement `fetch_metar()` and `fetch_taf()` methods
3. Add source type to `WeatherEngine._initialize()`

### Adding New Injection Methods

1. Create class inheriting from `WeatherInjector`
2. Implement `inject_weather()` method
3. Add injector selection logic to `WeatherEngine._initialize()`

### Adding New Smoothing Algorithms

1. Extend `WeatherSmoother` class
2. Override `smooth()` method or add new smoothing methods
3. Add configuration options to `SmoothingConfig`

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-19
