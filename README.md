# FSX Weather Bridge

A real-time weather injection system for Microsoft Flight Simulator X (FSX) that fetches real-world aviation weather data and injects it into the simulator via FSUIPC.

## Features

- 🌤️ **Real-time Weather Injection**: Automatically fetches and injects current METAR weather data from AviationWeather.gov
- 🎯 **Smart Station Selection**: Automatically selects nearby weather stations based on aircraft position
- 🌊 **Smooth Transitions**: Gradual weather changes prevent abrupt transitions that can cause unrealistic flight behavior
- 📊 **Interactive Web Interface**: Modern web-based UI for monitoring and configuration
- 🗺️ **Map Visualization**: Interactive map showing aircraft position and weather stations
- 📡 **TAF Support**: Optional TAF (Terminal Aerodrome Forecast) integration for forecast data
- 🔧 **Manual Weather Mode**: Override automatic weather with manual METAR/TAF input

## Requirements

- **Windows** (tested on Windows 10/11)
- **Python 3.12 (32-bit)** - ⚠️ **Must be 32-bit**, not 64-bit
- **Microsoft Flight Simulator X (FSX)**
- **FSUIPC4** - Must be installed and running

## Quick Start

1. **Install Python 3.12 (32-bit)**
   - Download from [python.org](https://www.python.org/downloads/)
   - ⚠️ Select "Windows installer (32-bit)" version
   - Verify: `python -VV` should show `Python 3.12.x (32-bit)`

2. **Install FSUIPC4**
   - Download from [Pete Dowson's website](http://www.fsuipc.com/)
   - Install in your FSX installation directory

3. **Install FSX Weather Bridge**
   ```bash
   # Run the installation script
   install.bat
   ```
   This will:
   - Detect and let you select your Python 3.12 (32-bit) installation
   - Install all required Python packages
   - Create configuration file

4. **Run the Application**
   - **Background Mode** (recommended): `run_hidden.bat`
   - **With Console**: `run.bat`
   - **As Administrator**: `run_admin.bat` (if needed)

5. **Access Web Interface**
   - Open browser to: `http://127.0.0.1:8080`
   - Or right-click system tray icon → "Open Web UI"

## Documentation

Comprehensive documentation is available in the [`Docs/`](Docs/) folder:

- **[Complete Documentation](Docs/README.md)** - Full system documentation
- **[Architecture](Docs/ARCHITECTURE.md)** - System architecture and design
- **[FSUIPC Offsets](Docs/FSUIPC_OFFSETS.md)** - Detailed FSUIPC offset reference
- **[Troubleshooting](Docs/TROUBLESHOOTING.md)** - Common issues and solutions

## How It Works

1. **Fetches Weather Data**: Downloads METAR/TAF data from AviationWeather.gov
2. **Selects Stations**: Chooses nearby weather stations based on aircraft position (from FSUIPC)
3. **Parses Weather**: Extracts wind, visibility, pressure, clouds, etc. from METAR strings
4. **Smooths Transitions**: Applies gradual changes to prevent abrupt weather updates
5. **Injects Weather**: Writes METAR strings to FSX via FSUIPC offset 0xB000
6. **Monitors Status**: Web UI provides real-time status, map, and configuration

## Configuration

Configuration is stored in `%USERPROFILE%\.fsweatherbridge\config.json` and can be modified via:
- **Web UI**: Navigate to Settings page
- **Config File**: Edit `config.json` directly

Key settings:
- Weather source and refresh rates
- Smoothing parameters (step-limited or time-based)
- Station selection radius
- FSUIPC connection settings
- Web UI host/port

See [Configuration Documentation](Docs/README.md#configuration) for details.

## System Tray

The application runs in the background with a system tray icon. Right-click for:
- **Open Web UI** - Opens the web interface
- **View Logs** - Opens the logs folder
- **Exit** - Shuts down the application

## Logging

All logs are written to files in the `logs/` directory:
- `fsweatherbridge.log` - Main application log
- `server.log` - Web server log
- `server_stdout.log` - Server stdout
- `server_stderr.log` - Server stderr

Logs are recreated fresh on each startup. View logs via:
- Web UI Logs page
- System tray menu → "View Logs"
- Direct file access in `logs/` folder

## Credits

This project uses the **fsuipc** Python library for FSUIPC communication:

- **Repository**: [https://github.com/tjensen/fsuipc](https://github.com/tjensen/fsuipc)
- **Author**: Tim Jensen
- **License**: MIT License

## License

This project is provided as-is. See individual component licenses:
- FSUIPC library: MIT License (see `fsuipc-master/LICENSE`)
- Python dependencies: Various (see `requirements.txt` and dependency licenses)

## Disclaimer

This software is provided "as-is" without warranty. Use at your own risk. The authors are not responsible for any damage or issues arising from the use of this software.

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

For issues, questions, or contributions:
- Check the [Troubleshooting Guide](Docs/TROUBLESHOOTING.md)
- Review the [Complete Documentation](Docs/README.md)
- Open an issue on GitHub

---

**Note**: This project requires Python 3.12 (32-bit) and FSUIPC4 for FSX. It has been tested with FSX only (not FS2020 or other simulators).
