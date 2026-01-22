# FSX Weather Bridge - Troubleshooting Guide

## Common Issues and Solutions

### FSUIPC Connection Issues

#### Problem: "FSUIPC initialization failed"

**Symptoms**:
- Application starts in DEV mode
- No weather injection occurs
- Log shows: "FSUIPC initialization failed: ..."

**Solutions**:

1. **Verify FSUIPC4 is installed**:
   - Check that FSUIPC4 is installed in your FSX directory
   - Ensure FSUIPC4.dll is present

2. **Check Python version**:
   ```bash
   python -VV
   ```
   Must show: `Python 3.12.x (32-bit)`
   - **Important**: 64-bit Python will NOT work with FSUIPC4

3. **Run as Administrator**:
   - Right-click `run_admin.bat` → "Run as administrator"
   - FSUIPC may require admin rights

4. **Verify FSX is running**:
   - FSUIPC4 only works when FSX is active
   - Start FSX before running Weather Bridge

5. **Check FSUIPC4 is active**:
   - In FSX, press `Alt` to show menu
   - Look for "Add-ons" → "FSUIPC" menu item
   - If missing, FSUIPC4 is not installed correctly

#### Problem: "FSUIPC connection lost"

**Symptoms**:
- Weather injection stops working
- Log shows: "FSUIPC connection lost, reconnecting..."

**Solutions**:

1. **Check FSX is still running**:
   - FSUIPC connection is lost if FSX closes

2. **Wait for auto-reconnect**:
   - System will attempt to reconnect every 5 seconds (configurable)
   - Check logs for reconnection status

3. **Restart application**:
   - If auto-reconnect fails, restart Weather Bridge
   - Ensure FSX is running before starting

### Weather Injection Not Working

#### Problem: Weather doesn't change in FSX

**Symptoms**:
- Application shows "Connected" and "Injection: Success"
- But weather in FSX doesn't change

**Solutions**:

1. **Check FSUIPC offset**:
   - Verify FSUIPC4 is version 4.x (not 5.x or 6.x)
   - Offset 0xB000 is for FSUIPC4

2. **Check METAR format**:
   - View logs to see generated METAR strings
   - Ensure METAR format is valid

3. **Verify station selection**:
   - Check web UI map to see selected stations
   - Ensure stations have valid METAR data

4. **Check smoothing**:
   - Smoothing may make changes very gradual
   - Check smoothing settings in configuration
   - Try disabling smoothing temporarily to test

5. **FSX Weather Settings**:
   - In FSX, ensure weather is set to "Custom" or "Real-world"
   - Some weather modes may override injected weather

#### Problem: Weather changes too abruptly

**Symptoms**:
- Weather changes instantly, causing unrealistic flight behavior

**Solutions**:

1. **Enable smoothing**:
   - Go to Settings → Smoothing
   - Ensure smoothing is enabled
   - Adjust smoothing parameters:
     - Reduce `max_wind_speed_change_kt` (e.g., 1.0 kt)
     - Reduce `max_wind_dir_change_deg` (e.g., 2.0°)
     - Reduce `max_qnh_change_hpa` (e.g., 0.2 hPa)

2. **Use time-based smoothing**:
   - Set `transition_mode` to `"time_based"`
   - Adjust `transition_interval_seconds` (e.g., 60 seconds)
   - Set smaller step sizes (e.g., `visibility_step_m: 100`)

3. **Increase update frequency**:
   - More frequent updates = smoother transitions
   - But may increase CPU usage

### Weather Data Issues

#### Problem: "No stations found"

**Symptoms**:
- Web UI shows "No stations selected"
- Weather injection uses global weather

**Solutions**:

1. **Check aircraft position**:
   - Ensure FSUIPC is connected and reading position
   - Check web UI status page for aircraft coordinates

2. **Increase search radius**:
   - Go to Settings → Station Selection
   - Increase `radius_nm` (e.g., 100 nm)

3. **Check station database**:
   - Verify `data/stations_full.json` exists
   - Check file size (should be several MB)
   - If missing, application will download on startup

4. **Enable fallback**:
   - Ensure `fallback_to_global` is enabled
   - System will use global weather if no stations found

#### Problem: "METAR data is stale"

**Symptoms**:
- Logs show: "METAR cache file is stale"
- Weather data may be outdated

**Solutions**:

1. **Check internet connection**:
   - Application needs internet to fetch fresh data
   - Verify AviationWeather.gov is accessible

2. **Reduce cache duration**:
   - Go to Settings → Weather Source
   - Reduce `cache_seconds` (e.g., 30 seconds)

3. **Force refresh**:
   - Restart application to force data download
   - Or wait for automatic refresh (every 60 seconds for METAR)

#### Problem: "Failed to parse METAR"

**Symptoms**:
- Logs show parsing errors
- Some stations show no weather data

**Solutions**:

1. **Check METAR format**:
   - Some non-standard METAR formats may not parse
   - Check raw METAR in logs

2. **Update parser**:
   - Parser is pragmatic, not full ICAO-compliant
   - Some edge cases may not be handled

3. **Use manual weather**:
   - For problematic stations, use manual weather mode
   - Enter METAR manually via web UI

### Web UI Issues

#### Problem: Web UI not accessible

**Symptoms**:
- Cannot connect to `http://127.0.0.1:8080`
- Browser shows "Connection refused"

**Solutions**:

1. **Check server is running**:
   - Look for system tray icon
   - Check logs for server startup messages

2. **Check port**:
   - Verify port 8080 is not in use by another application
   - Change port in Settings → Web UI → Port

3. **Check firewall**:
   - Windows Firewall may block the connection
   - Add exception for Python or port 8080

4. **Check host**:
   - Ensure `host` is set to `127.0.0.1` (localhost)
   - If set to `0.0.0.0`, use `localhost` or actual IP

#### Problem: Map not loading

**Symptoms**:
- Map page shows blank or error
- No stations or aircraft visible

**Solutions**:

1. **Check internet connection**:
   - Map uses Leaflet.js and OpenStreetMap tiles
   - Requires internet for map tiles

2. **Check browser console**:
   - Open browser developer tools (F12)
   - Check for JavaScript errors

3. **Check WebSocket connection**:
   - Map updates via WebSocket
   - Verify WebSocket connection in browser console

4. **Clear browser cache**:
   - Old cached files may cause issues
   - Clear cache and reload page

### Performance Issues

#### Problem: High CPU usage

**Symptoms**:
- Application uses excessive CPU
- System becomes slow

**Solutions**:

1. **Reduce update frequency**:
   - Go to Settings → Web UI
   - Increase `update_interval_seconds` (e.g., 2.0 seconds)

2. **Reduce station count**:
   - Go to Settings → Station Selection
   - Reduce `max_stations` (e.g., 2 instead of 3)

3. **Disable map updates**:
   - Close map page if not needed
   - Map updates can be CPU-intensive

4. **Check smoothing**:
   - Complex smoothing calculations may use CPU
   - Simplify smoothing parameters if needed

#### Problem: High memory usage

**Symptoms**:
- Application uses excessive memory
- System becomes slow

**Solutions**:

1. **Clear log files**:
   - Delete old log files in `logs/` directory
   - Logs accumulate over time

2. **Reduce log buffer**:
   - Web UI log buffer is limited to 1000 entries
   - This is hardcoded, but shouldn't cause issues

3. **Check data files**:
   - Large archive files in `data/metar_archive/` and `data/taf_archive/`
   - Delete old archive files if needed

### Configuration Issues

#### Problem: Configuration not saving

**Symptoms**:
- Changes in web UI don't persist
- Settings revert on restart

**Solutions**:

1. **Check file permissions**:
   - Configuration file: `%USERPROFILE%\.fsweatherbridge\config.json`
   - Ensure application has write permissions

2. **Check file path**:
   - Verify configuration file path in logs
   - Ensure path is accessible

3. **Manual edit**:
   - Edit `config.json` directly
   - Ensure valid JSON format
   - Restart application

#### Problem: Invalid configuration values

**Symptoms**:
- Application fails to start
- Logs show configuration errors

**Solutions**:

1. **Check JSON format**:
   - Ensure `config.json` is valid JSON
   - Use JSON validator if needed

2. **Check value ranges**:
   - See [Configuration](#configuration) section in main README
   - Ensure all values are within allowed ranges

3. **Reset to defaults**:
   - Delete `config.json`
   - Application will create default configuration on restart

### Logging Issues

#### Problem: No log files created

**Symptoms**:
- `logs/` directory is empty
- No logging output

**Solutions**:

1. **Check directory permissions**:
   - Ensure application can write to `logs/` directory
   - Check file permissions

2. **Check log directory exists**:
   - Application creates `logs/` on startup
   - If missing, create manually

3. **Check startup logs**:
   - Early startup logs may go to console (if console is visible)
   - Check console output if available

#### Problem: Log files too large

**Symptoms**:
- Log files grow very large
- Disk space issues

**Solutions**:

1. **Delete old logs**:
   - Logs are recreated on each startup
   - Delete log files before starting application

2. **Reduce log verbosity**:
   - Currently, log level is INFO
   - Can be changed in code (not configurable via UI yet)

3. **Manual cleanup**:
   - Periodically delete log files
   - Or set up scheduled task to clean logs

---

## Getting Help

### Log Files

When reporting issues, include:
- `logs/fsweatherbridge.log` - Main application log
- `logs/server.log` - Web server log
- `logs/server_stderr.log` - Error output

### System Information

Include:
- Python version: `python -VV`
- Windows version
- FSX version
- FSUIPC4 version
- Application version (check logs)

### Reproduction Steps

Describe:
1. What you were doing when the issue occurred
2. Expected behavior
3. Actual behavior
4. Steps to reproduce (if possible)

---

## Known Limitations

1. **Python 32-bit Required**: 64-bit Python will not work with FSUIPC4
2. **FSX Only**: Only tested with FSX (not FS2020 or other simulators)
3. **METAR Parser**: Pragmatic parser, not full ICAO-compliant (some edge cases may not parse)
4. **Single Aircraft**: Designed for single aircraft (not multiplayer)
5. **Windows Only**: Requires Windows (FSUIPC4 is Windows-only)

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-19
