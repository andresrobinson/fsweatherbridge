# FSX Weather Bridge - Complete Documentation

## Table of Contents

1. [System Overview](#system-overview)
2. [Requirements](#requirements)
3. [Architecture](#architecture)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Features](#features)
7. [Weather Data Sources](#weather-data-sources)
8. [METAR and TAF Parsing](#metar-and-taf-parsing)
9. [Weather Smoothing Logic](#weather-smoothing-logic)
10. [Weather Injection Logic](#weather-injection-logic)
11. [FSUIPC Integration](#fsuipc-integration)
12. [Map Rendering](#map-rendering)
13. [Logging System](#logging-system)
14. [Libraries and Licensing](#libraries-and-licensing)
15. [Credits](#credits)

---

## System Overview

FSX Weather Bridge is a real-time weather injection system for Microsoft Flight Simulator X (FSX). It fetches real-world aviation weather data (METAR and TAF reports) from AviationWeather.gov, processes and smooths the data to prevent abrupt weather changes, and injects it into FSX via FSUIPC.

### Key Capabilities

- **Real-time Weather Injection**: Automatically fetches and injects current METAR weather data
- **Smooth Transitions**: Gradual weather changes to prevent jarring transitions
- **Station Selection**: Automatically selects nearby weather stations based on aircraft position
- **TAF Support**: Optional TAF (Terminal Aerodrome Forecast) integration for forecast data
- **Web Interface**: Modern web-based UI for monitoring and configuration
- **Map Visualization**: Interactive map showing aircraft position and weather stations
- **Manual Weather Mode**: Override automatic weather with manual METAR/TAF input

---

## Requirements

### System Requirements

- **Operating System**: Windows (tested on Windows 10/11)
- **Python**: Python 3.12 (32-bit version required)
  - **Important**: Must be 32-bit Python, not 64-bit
  - FSX and FSUIPC4 are 32-bit applications, requiring 32-bit Python for compatibility
- **Flight Simulator**: Microsoft Flight Simulator X (FSX)
- **FSUIPC**: FSUIPC4 (version 4.x) must be installed and running
  - FSUIPC4 is a third-party addon that enables communication between external programs and FSX
  - Available from [Pete Dowson's website](http://www.fsuipc.com/)

### Python Dependencies

All dependencies are listed in `requirements.txt` and will be installed automatically during setup:

- `fastapi>=0.104.0` - Web framework for the UI
- `uvicorn[standard]>=0.24.0` - ASGI server
- `aiohttp>=3.9.0` - Async HTTP client for weather data fetching
- `pydantic>=2.0.0` - Data validation and configuration management
- `pystray>=0.19.0` - System tray icon support
- `Pillow>=10.0.0` - Image processing for tray icon
- `airportsdata>=2024.1.0` - Airport database for station name enhancement

### FSUIPC Library

The system uses a local copy of the `fsuipc` Python library (located in `fsuipc-master/` folder). This library provides the interface to FSUIPC4.

**Source**: [https://github.com/tjensen/fsuipc](https://github.com/tjensen/fsuipc)  
**License**: MIT License (see [Libraries and Licensing](#libraries-and-licensing))

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Web UI (FastAPI)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Status  │  │   Map    │  │ Settings │  │   Logs   │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  WeatherEngine (Core Logic)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Data Manager │  │ Weather      │  │ Weather      │      │
│  │              │  │ Source       │  │ Smoother     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ METAR/TAF    │  │ Weather      │  │ Station      │      │
│  │ Parser       │  │ Combiner     │  │ Database     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              FSUIPC Bridge & Weather Injector                │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ FSUIPC       │  │ Weather      │                        │
│  │ Bridge       │  │ Injector     │                        │
│  └──────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │   FSUIPC4    │
                    └──────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │     FSX      │
                    └──────────────┘
```

### Data Flow

1. **Weather Fetching**: `DataManager` fetches METAR/TAF data from AviationWeather.gov
2. **Station Selection**: `WeatherEngine` selects nearby stations based on aircraft position (from FSUIPC)
3. **Parsing**: `METARParser` and `TAFParser` parse raw weather strings
4. **Combining**: `WeatherCombiner` combines METAR and TAF according to configuration
5. **Smoothing**: `WeatherSmoother` applies gradual transitions to prevent abrupt changes
6. **Injection**: `WeatherInjector` writes weather data to FSX via FSUIPC offsets
7. **Monitoring**: Web UI displays status, map, and logs in real-time

---

## Installation

### Step 1: Install Python 3.12 (32-bit)

1. Download Python 3.12 32-bit from [python.org](https://www.python.org/downloads/)
2. **Important**: Select the "Windows installer (32-bit)" version
3. During installation, check "Add Python to PATH"
4. Verify installation:
   ```bash
   python -VV
   ```
   Should show: `Python 3.12.x (32-bit)`

### Step 2: Install FSUIPC4

1. Download FSUIPC4 from [Pete Dowson's website](http://www.fsuipc.com/)
2. Install FSUIPC4 in your FSX installation directory
3. Ensure FSUIPC4 is running when FSX is active

### Step 3: Install FSX Weather Bridge

1. Extract or clone the FSX Weather Bridge to a directory (e.g., `C:\wamp64\www\fsweatherbridge`)
2. Run `install.bat` to:
   - Select your Python 3.12 (32-bit) installation
   - Install all required Python packages
   - Create configuration file

### Step 4: Run the Application

- **Background Mode** (recommended): Run `run_hidden.bat` - starts without console window
- **With Console**: Run `run.bat` - shows console window (logs also go to files)
- **As Administrator**: Run `run_admin.bat` - may be needed if FSUIPC requires admin rights

The application will:
1. Start the web server on `http://127.0.0.1:8080`
2. Create a system tray icon
3. Connect to FSUIPC4 (if FSX is running)
4. Begin fetching and injecting weather data

---

## Configuration

Configuration is stored in `%USERPROFILE%\.fsweatherbridge\config.json` and can be modified via the web UI or by editing the file directly.

### Configuration Sections

#### Weather Source (`weather_source`)

Controls where weather data is fetched from.

```json
{
  "enabled": true,
  "source_type": "aviationweather",
  "cache_seconds": 45,
  "metar_refresh_seconds": 60,
  "taf_refresh_seconds": 600
}
```

- **enabled**: Enable/disable weather source
- **source_type**: Currently only `"aviationweather"` is supported
- **cache_seconds**: Cache duration for API responses (0-300 seconds)
- **metar_refresh_seconds**: How often to refresh METAR data (10-60 seconds)
- **taf_refresh_seconds**: How often to refresh TAF data (1-600 seconds)

#### Weather Combining (`weather_combining`)

Controls how METAR and TAF data are combined.

```json
{
  "mode": "metar_only",
  "taf_fallback_stale_seconds": 300
}
```

**Modes**:
- **`metar_only`**: Use METAR only, ignore TAF
- **`metar_taf_fallback`**: Use METAR if fresh, fallback to TAF if METAR is stale
- **`metar_taf_assist`**: Use METAR for current conditions, TAF for forecast guidance

- **taf_fallback_stale_seconds**: Age threshold (seconds) for considering METAR stale

#### Smoothing (`smoothing`)

Controls how weather transitions are smoothed to prevent abrupt changes.

```json
{
  "max_wind_dir_change_deg": 5.0,
  "max_wind_speed_change_kt": 2.0,
  "max_qnh_change_hpa": 0.5,
  "max_visibility_change": 0.5,
  "cloud_change_threshold": 1000.0,
  "transition_mode": "time_based",
  "transition_interval_seconds": 30.0,
  "visibility_step_m": 200.0,
  "wind_speed_step_kt": 2.0,
  "wind_dir_step_deg": 5.0,
  "qnh_step_hpa": 0.5,
  "approach_freeze_alt_ft": 1000.0,
  "big_change_wind_deg": 30.0,
  "big_change_wind_speed_kt": 10.0,
  "big_change_qnh_hpa": 5.0
}
```

**Transition Modes**:
- **`step_limited`**: Changes are limited per update cycle (original behavior)
- **`time_based`**: Changes occur gradually over time intervals (recommended)

**Key Parameters**:
- **max_wind_dir_change_deg**: Maximum wind direction change per cycle (0-180°)
- **max_wind_speed_change_kt**: Maximum wind speed change per cycle (0-50 kt)
- **max_qnh_change_hpa**: Maximum pressure change per cycle (0-10 hPa)
- **max_visibility_change**: Maximum visibility change per cycle (in nautical miles)
- **transition_interval_seconds**: Time between transition steps in time-based mode (10-300 seconds)
- **visibility_step_m**: Visibility change per step in meters (50-1000m)
- **wind_speed_step_kt**: Wind speed change per step (0.5-10 kt)
- **wind_dir_step_deg**: Wind direction change per step (1-30°)
- **qnh_step_hpa**: Pressure change per step (0.1-2.0 hPa)
- **approach_freeze_alt_ft**: Altitude below which weather is frozen (prevents changes during approach)

#### Station Selection (`station_selection`)

Controls how weather stations are selected.

```json
{
  "radius_nm": 50.0,
  "max_stations": 3,
  "fallback_to_global": true
}
```

- **radius_nm**: Search radius in nautical miles (0-500 nm)
- **max_stations**: Maximum number of stations to use (1-10)
- **fallback_to_global**: If no nearby stations found, use global weather

#### Manual Weather (`manual_weather`)

Allows manual override of automatic weather.

```json
{
  "enabled": false,
  "mode": "station",
  "icao": null,
  "raw_metar": null,
  "raw_taf": null,
  "freeze": false
}
```

- **enabled**: Enable manual weather mode
- **mode**: `"station"` (use ICAO code) or `"report"` (use raw METAR/TAF)
- **icao**: Station ICAO code (e.g., "KJFK")
- **raw_metar**: Raw METAR string
- **raw_taf**: Raw TAF string
- **freeze**: Freeze weather (prevent automatic updates)

#### FSUIPC (`fsuipc`)

Controls FSUIPC connection.

```json
{
  "enabled": true,
  "dev_mode": false,
  "auto_reconnect": true,
  "reconnect_interval_seconds": 5.0
}
```

- **enabled**: Enable FSUIPC connection
- **dev_mode**: Development mode (simulated aircraft data, no actual injection)
- **auto_reconnect**: Automatically reconnect if connection is lost
- **reconnect_interval_seconds**: How often to attempt reconnection (1-60 seconds)

#### Web UI (`web_ui`)

Controls the web interface.

```json
{
  "host": "127.0.0.1",
  "port": 8080,
  "update_interval_seconds": 1.0
}
```

- **host**: Web server host (usually `127.0.0.1` for localhost)
- **port**: Web server port (1024-65535)
- **update_interval_seconds**: WebSocket update interval (0.1-10.0 seconds)

---

## Features

### Real-time Weather Injection

- Automatically fetches current METAR data from AviationWeather.gov
- Selects nearby weather stations based on aircraft position
- Injects weather into FSX via FSUIPC offset 0xB000
- Updates weather every 60 seconds (configurable)

### Weather Smoothing

- Gradual transitions prevent abrupt weather changes
- Two smoothing modes: step-limited and time-based
- Automatic detection of "big changes" for faster transitions
- Freeze logic prevents weather changes during approach (below 1000 ft AGL)

### Web Interface

- **Status Page**: Real-time system status, aircraft position, selected stations, current weather
- **Map Page**: Interactive map showing:
  - Aircraft position (blue marker)
  - Selected weather stations (colored markers)
  - Wind direction indicators
  - Station details on click
- **Settings Page**: Configure all system parameters
- **Logs Page**: View real-time application logs
- **Manual Weather Page**: Override automatic weather with manual METAR/TAF
- **Stored Weather Page**: View and manage stored weather data

### System Tray Integration

- Runs in background with system tray icon
- Right-click menu:
  - Open Web UI
  - View Logs (opens logs folder)
  - Exit

### Data Persistence

- Station database cached locally
- METAR/TAF data cached and archived
- Configuration persisted to user profile
- Automatic data refresh and cleanup

---

## Weather Data Sources

### AviationWeather.gov

The system fetches weather data from the AviationWeather.gov API:

- **METAR Data**: Current weather observations
  - URL: `https://aviationweather.gov/api/data/metar`
  - Cache file: `https://aviationweather.gov/data/cache/metar.cache.csv.gz`
  - Refresh rate: Every 60 seconds (configurable)

- **TAF Data**: Terminal Aerodrome Forecasts
  - URL: `https://aviationweather.gov/api/data/taf`
  - Cache file: `https://aviationweather.gov/data/cache/taf.cache.csv.gz`
  - Refresh rate: Every 600 seconds (10 minutes, configurable)

- **Station List**: Airport/weather station database
  - URL: `https://aviationweather.gov/data/cache/stations.cache.json.gz`
  - Refresh rate: Once per day

### Data Caching

- **Stations**: Cached for 24 hours
- **METAR**: Cached for 1 hour
- **TAF**: Cached for 1 hour
- **Airport Names**: Cached for 7 days

All cached data is stored in the `data/` directory:
- `data/stations_full.json` - Station database
- `data/metar_latest.json` - Latest METAR data
- `data/taf_latest.json` - Latest TAF data
- `data/metar_archive/` - Historical METAR archives
- `data/taf_archive/` - Historical TAF archives

---

## METAR and TAF Parsing

### METAR Parsing Strategy

The METAR parser (`src/metar_parser.py`) uses a pragmatic, regex-based approach to extract key weather parameters from METAR strings.

#### Parsed Fields

- **ICAO Code**: 4-letter station identifier
- **Wind Direction**: Degrees (0-360) or `None` for variable
- **Wind Speed**: Knots
- **Wind Gust**: Knots (if present)
- **Visibility**: Nautical miles
- **Temperature**: Celsius
- **Dewpoint**: Celsius
- **QNH**: Hectopascals (sea level pressure)
- **Altimeter**: Inches of mercury
- **Clouds**: List of cloud layers (coverage, base altitude)
- **Weather Tokens**: Present weather codes (e.g., "RA", "SN", "FG")

#### Parsing Logic

1. **ICAO Extraction**: Finds 4-letter code after "METAR" keyword or as first token
2. **Wind Parsing**: Regex pattern `(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT`
   - Handles variable wind (`VRB`)
   - Extracts direction, speed, and gust
3. **Visibility Parsing**: Handles various formats:
   - Statute miles (e.g., "10SM")
   - Kilometers (e.g., "9999" = 10+ km)
   - Fractional (e.g., "1/2SM")
4. **Temperature/Dewpoint**: Extracts from format like "M05/M07" (negative temps)
5. **Pressure Parsing**: Handles both QNH (Q####) and altimeter (A####) formats
6. **Cloud Parsing**: Extracts cloud layers:
   - Coverage: FEW, SCT, BKN, OVC
   - Base: Altitude in feet (e.g., "BKN030" = broken at 3000 ft)
7. **Weather Codes**: Extracts present weather tokens (e.g., "RA", "SN", "FG", "BR")

#### Limitations

- Not a full ICAO-compliant parser
- Some non-standard METAR formats may not parse correctly
- Complex weather phenomena may be simplified

### TAF Parsing Strategy

The TAF parser (`src/taf_parser.py`) extracts forecast groups from TAF strings.

#### Parsed Structure

- **ICAO Code**: Station identifier
- **Issue Time**: When the TAF was issued
- **Valid From/To**: Validity period
- **Prevailing Group**: Main forecast conditions
- **Groups**: Additional forecast groups (FM, TEMPO, PROB)

#### Parsing Logic

1. **Header Parsing**: Extracts ICAO, issue time, and validity period
2. **Group Parsing**: Identifies forecast groups:
   - **FM** (From): Specific time periods
   - **TEMPO** (Temporary): Temporary conditions
   - **PROB** (Probability): Probabilistic forecasts
3. **Weather Extraction**: Similar to METAR parsing for each group
4. **Time Handling**: Handles date rollover (month boundaries)

#### Usage

TAF data is used in three modes:
1. **metar_only**: TAF is ignored
2. **metar_taf_fallback**: TAF used if METAR is stale
3. **metar_taf_assist**: TAF provides forecast guidance for future conditions

---

## Weather Smoothing Logic

Weather smoothing prevents abrupt weather changes that can cause unrealistic flight behavior. The smoothing engine (`src/weather_smoother.py`) implements gradual transitions.

### Smoothing Modes

#### Step-Limited Mode (`step_limited`)

Changes are limited per update cycle. For example:
- Wind speed can change by max 2 kt per cycle
- If target is 20 kt and current is 10 kt, it takes 5 cycles to reach target

**Use Case**: Predictable, consistent transitions

#### Time-Based Mode (`time_based`) - Recommended

Changes occur gradually over time intervals. For example:
- Visibility changes by 200m every 30 seconds
- Wind speed changes by 2 kt every 30 seconds
- More realistic, time-based transitions

**Use Case**: More realistic weather transitions that respect time

### Smoothing Parameters

#### Wind Direction

- Handles wraparound (0° = 360°)
- Maximum change per step: `wind_dir_step_deg` (default: 5°)
- For big changes (>30°), uses 10x normal rate
- For very big changes (>20 kt speed or >10 nm visibility), uses 50x normal rate

#### Wind Speed

- Maximum change per step: `wind_speed_step_kt` (default: 2 kt)
- Gust speed smoothed similarly

#### Pressure (QNH)

- Maximum change per step: `qnh_step_hpa` (default: 0.5 hPa)
- Prevents rapid pressure changes

#### Visibility

- Maximum change per step: `visibility_step_m` (default: 200m)
- Converted from meters to nautical miles for injection

#### Temperature/Dewpoint

- **No smoothing** - Changes instantly
- Temperature changes are typically gradual in real weather

#### Clouds

- Simple threshold-based smoothing
- Cloud layers added/removed when base altitude changes by >1000 ft

### Big Change Detection

The system detects "big changes" that warrant faster transitions:

- **Wind Direction**: Change >30°
- **Wind Speed**: Change >10 kt
- **QNH**: Change >5 hPa
- **Visibility**: Change >5 nm, or transition from <1 nm to >5 nm (or vice versa)
- **Clouds**: Transition from overcast to clear (or vice versa)

When a big change is detected:
- Smoothing limits are increased 10x (big change) or 50x (very big change)
- Allows faster transition to new conditions
- Prevents extended periods of unrealistic intermediate weather

### Freeze Logic

During approach (below `approach_freeze_alt_ft`, default 1000 ft AGL):
- Weather changes are frozen to prevent distractions
- Freeze is broken if:
  - Current state is uninitialized (first injection)
  - A "big change" is detected (safety override)

This prevents weather changes during critical approach phases.

### Smoothing State

The smoother maintains a `WeatherState` object representing the last injected weather:
- Used as the starting point for each transition
- Updated after each successful injection
- Persisted across application restarts (via injection state)

---

## Weather Injection Logic

Weather injection writes weather data to FSX via FSUIPC. The injector (`src/weather_injector.py`) supports multiple injection methods.

### FSUIPC Weather Injection (Primary Method)

#### Offset 0xB000

The system uses FSUIPC offset **0xB000** to inject METAR strings directly into FSX. This is the recommended method per FSUIPC documentation.

**How it works**:
1. Weather data is converted to a METAR string
2. METAR string is written to FSUIPC offset 0xB000 (256 bytes max)
3. FSUIPC forwards the METAR to SimConnect
4. FSX applies the weather

#### METAR String Format

The injector generates METAR strings in the format:
```
METAR ICAO YYMMDDHHMMZ WIND VIS TEMP/DEW QNH CLOUDS WX
```

Example:
```
METAR KJFK 191200Z 12015KT 10SM OVC030 15/10 Q1013
```

#### Station-Based Injection

When aircraft is near a weather station:
- Uses the station's ICAO code in the METAR
- Injects weather for that specific station
- FSX applies weather in a radius around that station

#### Global Injection

When no nearby stations are found:
- Uses "GLOB" as the ICAO code
- Injects global weather
- Applies weather worldwide

### Injection Frequency

- Weather is injected every update cycle (typically every 1-2 seconds)
- Only injects if weather has changed (smoothed state differs from last injected)
- Logs injection attempts and results

### Error Handling

- If FSUIPC connection is lost, attempts auto-reconnect
- If injection fails, logs error and retries on next cycle
- Falls back to DEV mode if FSUIPC is unavailable

### DEV Mode

When FSUIPC is not available:
- Uses `DEVInjector` class
- Logs weather data instead of injecting
- Useful for testing and development

---

## FSUIPC Integration

### FSUIPC Bridge

The `FSUIPCBridge` class (`src/fsuipc_bridge.py`) manages the connection to FSUIPC4 and reads aircraft state data.

### FSUIPC Offsets Used

#### Aircraft Position and State

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0x0560 | 4 bytes | Unsigned 32-bit | Latitude (low 32 bits) |
| 0x0564 | 4 bytes | Signed 32-bit | Latitude (high 32 bits) |
| 0x0568 | 4 bytes | Unsigned 32-bit | Longitude (low 32 bits) |
| 0x056C | 4 bytes | Signed 32-bit | Longitude (high 32 bits) |
| 0x0570 | 4 bytes | Unsigned 32-bit | Altitude (low 32 bits, fractional metres) |
| 0x0574 | 4 bytes | Signed 32-bit | Altitude (high 32 bits, integer metres) |
| 0x02B4 | 4 bytes | Unsigned 32-bit | Ground speed (metres/sec * 65536) |
| 0x02B8 | 4 bytes | Signed 32-bit | Vertical speed (feet/min * 256) |
| 0x0580 | 4 bytes | Unsigned 32-bit | True heading (degrees * 2^32 / 360) |
| 0x02A0 | 2 bytes | Signed 16-bit | Magnetic variation (degrees, negative = West) |
| 0x0366 | 2 bytes | Unsigned 16-bit | On ground flag (1 = on ground) |

#### Weather Injection

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0xB000 | 256 bytes | String | METAR string for weather injection |

### Data Conversion

#### Latitude/Longitude

Latitude and longitude are stored as 64-bit signed integers:
- **Format**: `degrees * 2^32 / 360`
- **Reading**: Split into high/low 32-bit values
- **Conversion**: `(high_32 << 32) + low_32` then divide by `2^32 / 360`

#### Altitude

Altitude is stored as 64-bit signed integer:
- **Format**: `feet * 256`
- **Reading**: Split into high/low 32-bit values
- **High 32 bits**: Integer metres (signed)
- **Low 32 bits**: Fractional metres (unsigned)
- **Conversion**: Combine and convert to feet

#### Ground Speed

- **Format**: `metres/sec * 65536`
- **Conversion**: Divide by 65536, then convert m/s to knots

#### Vertical Speed

- **Format**: `feet/min * 256`
- **Conversion**: Divide by 256

#### Heading

- **Format**: `degrees * 2^32 / 360`
- **Conversion**: Multiply by 360 and divide by `2^32`

### Connection Management

- **Auto-Connect**: Attempts to connect on initialization
- **Auto-Reconnect**: Automatically reconnects if connection is lost
- **Reconnect Interval**: Configurable (default: 5 seconds)
- **Error Handling**: Graceful degradation to DEV mode if FSUIPC unavailable

### FSUIPC Library

The system uses the `fsuipc` Python library from [https://github.com/tjensen/fsuipc](https://github.com/tjensen/fsuipc).

**Key Features**:
- Context manager support (`with FSUIPC() as fsuipc:`)
- Prepared data reading for efficient multi-offset reads
- Type-safe offset reading/writing
- Error handling via `FSUIPCException`

**Usage Example**:
```python
from fsuipc import FSUIPC, FSUIPCException

with FSUIPC() as fsuipc:
    prepared = fsuipc.prepare_data([
        (0x560, "u"),  # Latitude low
        (0x564, "d"),  # Latitude high
        # ... more offsets
    ], True)
    
    lat_low, lat_high, ... = prepared.read()
```

---

## Map Rendering

The map page (`templates/map.html`) provides an interactive visualization of aircraft position and weather stations.

### Map Library

Uses **Leaflet.js** (v1.9.4) for map rendering:
- **Tile Source**: OpenStreetMap
- **License**: OpenStreetMap data is ODbL licensed

### Map Features

#### Aircraft Marker

- **Color**: Blue
- **Icon**: Custom aircraft icon
- **Updates**: Real-time position updates via WebSocket
- **Auto-Centering**: Map centers on aircraft on first load

#### Station Markers

- **Colors**: Based on station status
  - Green: Active, has current METAR
  - Yellow: Active, METAR may be stale
  - Red: Inactive or no METAR
- **Click**: Shows station details popup
- **Visibility**: Only shown at zoom levels 8+ (regional view)

#### Wind Indicators

- **Display**: Wind direction arrows at station locations
- **Visibility**: Only shown at zoom levels 10+ (detailed view)
- **Color**: Matches station marker color
- **Length**: Proportional to wind speed

#### Station Details Popup

When clicking a station marker:
- Station ICAO code
- Station name
- Distance from aircraft
- Current METAR (if available)
- Wind direction and speed
- Visibility
- Clouds
- Temperature

### Map Controls

- **Zoom**: Mouse wheel or +/- buttons
- **Pan**: Click and drag
- **Auto-Update**: Map updates every second via WebSocket
- **Responsive**: Adapts to window size

### Performance Optimizations

- **Lazy Loading**: Station markers only loaded at appropriate zoom levels
- **Marker Caching**: Markers are cached and reused
- **Update Throttling**: WebSocket updates throttled to prevent excessive redraws
- **Viewport Culling**: Only stations in viewport are rendered (at high zoom)

---

## Logging System

The system uses Python's `logging` module with file-based logging (no console output).

### Log Files

All logs are stored in the `logs/` directory:

- **`fsweatherbridge.log`**: Main application log
- **`server.log`**: Web server (Uvicorn) log
- **`server_stdout.log`**: Server stdout output
- **`server_stderr.log`**: Server stderr output

### Log Rotation

- **At Startup**: All log files are deleted and recreated (fresh start each run)
- **No Rotation**: Logs accumulate during a session
- **Manual Cleanup**: User can delete log files manually

### Log Levels

- **INFO**: Normal operation messages
- **WARNING**: Non-critical issues (e.g., FSUIPC connection lost)
- **ERROR**: Errors that don't stop operation
- **CRITICAL**: Fatal errors

### Log Format

```
%(asctime)s - %(levelname)s:%(name)s:%(message)s
```

Example:
```
2024-01-19 12:00:00,123 - INFO:src.app_core:WeatherEngine initialized
2024-01-19 12:00:01,456 - WARNING:src.fsuipc_bridge:FSUIPC connection lost, reconnecting...
```

### Web UI Logs

The web UI (`/logs` page) displays:
- Real-time log entries via WebSocket
- Filterable by log level
- Last 1000 entries kept in memory
- Auto-scroll to latest entries

### Accessing Logs

1. **Via Web UI**: Navigate to "Logs" page
2. **Via System Tray**: Right-click icon → "View Logs" (opens logs folder)
3. **Direct Access**: Open `logs/` folder in file explorer

---

## Libraries and Licensing

### Python Dependencies

#### FastAPI
- **Version**: >=0.104.0
- **License**: MIT License
- **Purpose**: Web framework for REST API and WebSocket support
- **URL**: https://fastapi.tiangolo.com/

#### Uvicorn
- **Version**: >=0.24.0 (with standard extras)
- **License**: BSD License
- **Purpose**: ASGI server for FastAPI
- **URL**: https://www.uvicorn.org/

#### aiohttp
- **Version**: >=3.9.0
- **License**: Apache License 2.0
- **Purpose**: Async HTTP client for weather data fetching
- **URL**: https://docs.aiohttp.org/

#### Pydantic
- **Version**: >=2.0.0
- **License**: MIT License
- **Purpose**: Data validation and configuration management
- **URL**: https://docs.pydantic.dev/

#### pystray
- **Version**: >=0.19.0
- **License**: LGPL-3.0 License
- **Purpose**: System tray icon support
- **URL**: https://github.com/moses-palmer/pystray

#### Pillow (PIL)
- **Version**: >=10.0.0
- **License**: PIL License (open source)
- **Purpose**: Image processing for tray icon
- **URL**: https://pillow.readthedocs.io/

#### airportsdata
- **Version**: >=2024.1.0
- **License**: MIT License
- **Purpose**: Airport database for station name enhancement
- **URL**: https://github.com/mborsetti/airportsdata

### FSUIPC Library

#### fsuipc (Python)
- **Source**: [https://github.com/tjensen/fsuipc](https://github.com/tjensen/fsuipc)
- **License**: MIT License
- **Author**: Tim Jensen
- **Purpose**: Python wrapper for FSUIPC communication
- **Location**: `fsuipc-master/` folder (local copy)

**MIT License Text**:
```
MIT License

Copyright (c) 2020 Tim Jensen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Map Libraries

#### Leaflet.js
- **Version**: 1.9.4
- **License**: BSD 2-Clause License
- **Purpose**: Interactive map rendering
- **URL**: https://leafletjs.com/

#### OpenStreetMap
- **Tile Source**: OpenStreetMap
- **License**: Open Database License (ODbL)
- **Purpose**: Map tile provider
- **URL**: https://www.openstreetmap.org/

### Third-Party Services

#### AviationWeather.gov
- **Service**: METAR/TAF weather data API
- **License**: Public domain (US government data)
- **Purpose**: Source of real-world weather data
- **URL**: https://aviationweather.gov/

---

## Credits

### FSUIPC Library

This project uses the **fsuipc** Python library for FSUIPC communication:

**Repository**: [https://github.com/tjensen/fsuipc](https://github.com/tjensen/fsuipc)  
**Author**: Tim Jensen  
**License**: MIT License

The library provides a clean Python interface to FSUIPC4, enabling communication between Python applications and Microsoft Flight Simulator X.

### FSUIPC4

FSUIPC4 is a third-party addon for FSX that enables external programs to communicate with the simulator:

**Developer**: Pete Dowson  
**Website**: http://www.fsuipc.com/  
**License**: Commercial (requires purchase for full features)

FSX Weather Bridge requires FSUIPC4 to be installed and running for weather injection to work.

### AviationWeather.gov

Weather data is provided by the Aviation Weather Center (AWC), part of the National Weather Service:

**Website**: https://aviationweather.gov/  
**Data License**: Public domain (US government data)

---

## Additional Documentation

For more detailed information on specific components, see:

- **FSUIPC Offsets Reference**: See [FSUIPC Integration](#fsuipc-integration) section
- **Configuration Reference**: See [Configuration](#configuration) section
- **API Documentation**: Available via FastAPI's automatic docs at `http://127.0.0.1:8080/docs`

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-19
