"""FSUIPC integration for FSX."""

import sys
import time
from pathlib import Path
from typing import Dict, Optional

# Import from local fsuipc-master
sys.path.insert(0, str(Path(__file__).parent.parent / "fsuipc-master"))

FSUIPC_IMPORT_ERROR = None
try:
    from fsuipc import FSUIPC, FSUIPCException
    FSUIPC_AVAILABLE = True
except (ImportError, OSError, ModuleNotFoundError) as e:
    # FSUIPC not available - could be missing module, wrong Python version, or missing .pyd file
    FSUIPC_AVAILABLE = False
    FSUIPC = None
    FSUIPCException = Exception
    FSUIPC_IMPORT_ERROR = str(e)

from src.config import FSUIPCConfig
from src.utils import require_32bit_python


class AircraftState:
    """Aircraft state data."""
    
    def __init__(self):
        self.lat: float = 0.0
        self.lon: float = 0.0
        self.alt_ft: float = 0.0
        self.gs_kt: float = 0.0
        self.vs_fpm: float = 0.0
        self.heading_deg: float = 0.0
        self.on_ground: bool = True
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "lat": self.lat,
            "lon": self.lon,
            "alt_ft": self.alt_ft,
            "gs_kt": self.gs_kt,
            "vs_fpm": self.vs_fpm,
            "heading_deg": self.heading_deg,
            "on_ground": self.on_ground,
        }


class FSUIPCBridge:
    """Bridge to FSUIPC for FSX."""
    
    def __init__(self, config: FSUIPCConfig):
        self.config = config
        self.connection: Optional[FSUIPC] = None
        self.connected = False
        self.dev_mode = config.dev_mode
        self._cached_connection_status = False  # Cached status to prevent flickering
        self._last_connection_check = 0.0  # Timestamp of last connection check
        self._connection_check_interval = 5.0  # Only check connection status every 5 seconds (prevents flickering)
        
        # FSUIPC offsets for FSX
        # Latitude: 0x0560 (8 bytes, signed 64-bit, degrees * 2^32 / 360)
        # Longitude: 0x0568 (8 bytes, signed 64-bit, degrees * 2^32 / 360)
        # Altitude: 0x0570 (8 bytes, signed 64-bit, feet * 256)
        # Ground speed: 0x02B4 (4 bytes, signed 32-bit, knots * 65536 / 3600)
        # Vertical speed: 0x02B8 (4 bytes, signed 32-bit, feet/min * 256)
        # Heading: 0x0580 (8 bytes, unsigned 64-bit, degrees * 2^32 / 360)
        # On ground: 0x0366 (2 bytes, unsigned 16-bit, 1 = on ground)
        
        if not self.dev_mode:
            # Enforce 32-bit Python requirement
            require_32bit_python()
        
        if not FSUIPC_AVAILABLE and not self.dev_mode:
            # Auto-enable DEV mode if FSUIPC is not available
            import logging
            logger = logging.getLogger(__name__)
            error_msg = FSUIPC_IMPORT_ERROR if FSUIPC_IMPORT_ERROR else "unknown error"
            logger.warning(f"FSUIPC library not available ({error_msg}).")
            logger.info("Enabling DEV mode automatically.")
            logger.info("To use FSUIPC, ensure fsuipc-master is in the project root and the .pyd file matches your Python version.")
            self.dev_mode = True
    
    def connect(self) -> bool:
        """Connect to FSUIPC."""
        if self.dev_mode:
            self.connected = True
            self._cached_connection_status = True  # Update cache
            self._last_connection_check = time.time()
            return True
        
        if not FSUIPC_AVAILABLE:
            return False
        
        try:
            self.connection = FSUIPC()
            self.connected = True
            self._cached_connection_status = True  # Update cache
            self._last_connection_check = time.time()
            return True
        except FSUIPCException as e:
            self.connected = False
            self._cached_connection_status = False  # Update cache
            self._last_connection_check = time.time()
            return False
    
    def reconnect(self) -> bool:
        """Reconnect to FSUIPC (disconnect first, then connect)."""
        self.disconnect()
        result = self.connect()
        # Force cache update after reconnect attempt
        self._last_connection_check = time.time()
        return result
    
    def disconnect(self) -> None:
        """Disconnect from FSUIPC."""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None
        self.connected = False
        self._cached_connection_status = False  # Update cache
        self._last_connection_check = time.time()
    
    def is_connected(self) -> bool:
        """Check if connected - verify both flag and connection object.
        
        Uses cached status to prevent flickering - only checks every 2 seconds.
        """
        if self.dev_mode:
            return self.connected
        
        # Use cached status to prevent flickering (only update every 2 seconds)
        current_time = time.time()
        if current_time - self._last_connection_check < self._connection_check_interval:
            return self._cached_connection_status
        
        # Update cached status
        self._last_connection_check = current_time
        try:
            # Verify both the flag and that connection object exists
            new_status = self.connected and self.connection is not None
            # Only update cache if status actually changed (prevents flickering)
            if new_status != self._cached_connection_status:
                self._cached_connection_status = new_status
            return self._cached_connection_status
        except Exception:
            # On any error, assume disconnected
            self._cached_connection_status = False
            return False
    
    def get_aircraft_state(self) -> Optional[AircraftState]:
        """
        Get current aircraft state.
        
        Returns:
            AircraftState object, or None if not connected or in DEV mode
        """
        if self.dev_mode:
            # Return simulated data in DEV mode
            return self._get_dev_state()
        
        if not self.connected or not self.connection:
            return None
        
        try:
            # Prepare data for reading
            # According to FSUIPC documentation, lat/lon/alt are 64-bit integers that need
            # to be split into high and low 32-bit parts for proper conversion
            # For 32-bit systems, lat/lon are split into high and low 32-bit parts
            # Latitude: low 32 bits (unsigned) at 0x0560, high 32 bits (signed) at 0x0564
            # Longitude: low 32 bits (unsigned) at 0x0568, high 32 bits (signed) at 0x056C
            prepared = self.connection.prepare_data([
                (0x560, "u"),  # Latitude low 32 bits (unsigned)
                (0x564, "d"),  # Latitude high 32 bits (signed)
                (0x568, "u"),  # Longitude low 32 bits (unsigned)
                (0x56C, "d"),  # Longitude high 32 bits (signed)
                (0x570, "u"),  # Altitude low 32 bits (unsigned, fractional metres)
                (0x574, "d"),  # Altitude high 32 bits (signed, integer metres)
                (0x2B4, "u"),  # Ground speed (32-bit unsigned int, metres/sec * 65536)
                (0x2B8, "d"),  # Vertical speed (32-bit signed int, feet/min * 256)
                (0x580, "u"),  # True Heading (32-bit unsigned)
                (0x2A0, "h"),  # Magnetic Variation (16-bit signed)
                (0x366, "H"),  # On ground (16-bit unsigned, 1 = on ground)
            ], True)
            
            data = prepared.read()
            
            # Ensure we have enough data elements
            if len(data) < 11:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"FSUIPC returned insufficient data: expected 11 elements, got {len(data)}")
                return None
            
            # Debug: log raw values and types (first time only, debug level)
            if not hasattr(self, '_debug_logged'):
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"FSUIPC raw values: lat={data[0]}/{data[1]}, lon={data[2]}/{data[3]}, alt={data[4]}/{data[5]}, gs={data[6]}, hdg={data[8]}")
                self._debug_logged = True
            
            state = AircraftState()
            
            # Convert FSUIPC values to standard units
            # For 32-bit systems, lat/lon are split into high and low 32-bit parts
            
            # Latitude: combine high and low 32-bit parts
            lat_low = data[0]   # Unsigned 32-bit at 0x0560
            lat_high = data[1]  # Signed 32-bit at 0x0564
            
            # Convert to doubles
            dHi_lat = float(lat_high)
            dLo_lat = float(lat_low)
            
            # Divide low part by (65536.0 * 65536.0) to give it proper magnitude
            dLo_lat = dLo_lat / (65536.0 * 65536.0)
            
            # Add or subtract according to whether dHi is positive or negative
            if dHi_lat >= 0:
                lat_combined = dHi_lat + dLo_lat
            else:
                lat_combined = dHi_lat - dLo_lat
            
            # Multiply by 90.0 / 10001750.0 to get degrees
            state.lat = lat_combined * 90.0 / 10001750.0
            
            # Longitude: combine high and low 32-bit parts
            # High 32 bits (signed) at 0x056C, low 32 bits (unsigned) at 0x0568
            lon_low = data[2]   # Unsigned 32-bit at 0x0568
            lon_high = data[3]  # Signed 32-bit at 0x056C
            
            # Convert to doubles
            dHi_lon = float(lon_high)
            dLo_lon = float(lon_low)
            
            # Divide low part by (65536.0 * 65536.0) to give it proper magnitude
            dLo_lon = dLo_lon / (65536.0 * 65536.0)
            
            # Add or subtract according to whether dHi is positive or negative
            if dHi_lon >= 0:
                lon_combined = dHi_lon + dLo_lon
            else:
                lon_combined = dHi_lon - dLo_lon
            
            # Multiply by 360.0 / (65536.0 * 65536.0) to get degrees
            # Negative result is West, positive is East
            state.lon = lon_combined * 360.0 / (65536.0 * 65536.0)
            
            # Debug: log raw values on first read to diagnose issues (only in debug mode)
            if not hasattr(self, '_latlon_debug_logged'):
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Lat/Lon conversion: lat={state.lat:.6f}, lon={state.lon:.6f}")
                self._latlon_debug_logged = True
            
            # Validate lat/lon
            if abs(state.lat) < 0.0001 and abs(state.lon) < 0.0001:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Lat/lon are essentially zero - may indicate uninitialized data or wrong conversion")
                logger.warning(f"Raw values: lat_low={lat_low}, lat_high={lat_high}, lon_low={lon_low}, lon_high={lon_high}")
                # If raw values are also zero, data is likely uninitialized - return None
                if lat_low == 0 and lat_high == 0 and lon_low == 0 and lon_high == 0:
                    logger.error("All lat/lon raw values are zero - FSX may not be running or data is uninitialized")
                    return None
                # Otherwise, continue with the zero values (might be valid if at 0,0)
            elif state.lat < -90 or state.lat > 90 or state.lon < -180 or state.lon > 180:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Converted lat/lon out of range: lat={state.lat}, lon={state.lon}")
                logger.warning(f"Raw values: lat_low={lat_low}, lat_high={lat_high}, lon_low={lon_low}, lon_high={lon_high}")
                # If way out of range, data might be uninitialized
                if abs(state.lat) > 1000 or abs(state.lon) > 1000:
                    logger.error("Values are way out of range - FSX may not be running or data is uninitialized")
                    return None
            
            # Altitude: split into high and low 32-bit parts
            # High 32 bits (signed) at 0x0574 = integer metres
            # Low 32 bits (unsigned) at 0x0570 = fractional metres
            alt_low = data[4]   # Unsigned 32-bit at 0x0570 (fractional metres)
            alt_high = data[5]  # Signed 32-bit at 0x0574 (integer metres)
            
            # Convert to doubles
            dHi_alt = float(alt_high)  # Integer metres
            dLo_alt = float(alt_low)   # Fractional metres
            
            # Divide low part by (65536.0 * 65536.0) to give it proper magnitude
            dLo_alt = dLo_alt / (65536.0 * 65536.0)
            
            # Combine: integer metres + fractional metres
            alt_meters = dHi_alt + dLo_alt
            
            # Convert to feet
            state.alt_ft = alt_meters * 3.28084
            
            # Ground speed: stored as metres/sec * 65536 (32-bit unsigned)
            # Convert: (raw / 65536) * 1.94384 = knots
            gs_raw = data[6]
            if gs_raw < 0:
                gs_raw = gs_raw + 2**32  # Handle as unsigned
            gs_mps = float(gs_raw) / 65536.0  # metres per second
            state.gs_kt = gs_mps * 1.94384  # Convert to knots
            
            # Vertical speed: stored as feet/min * 256, so fpm = value / 256
            state.vs_fpm = float(data[7]) / 256.0
            
            # Heading: 0x0580 is True Heading (32-bit unsigned)
            # Convert using: degrees = value * 360 / (65536 * 65536)
            # 0x02A0 is Magnetic Variation (16-bit signed, negative = West)
            # Convert using: degrees = value * 360 / 65536
            # Magnetic Heading = True Heading - Magnetic Variation
            heading_raw = data[8]
            mag_var_raw = data[9]
            
            # Convert true heading (32-bit unsigned)
            if isinstance(heading_raw, int):
                # Handle as unsigned 32-bit
                if heading_raw < 0:
                    heading_raw = heading_raw + 2**32
                # Use (65536 * 65536) for heading conversion
                true_heading = (float(heading_raw) * 360.0) / (65536.0 * 65536.0)
            else:
                true_heading = float(heading_raw)
            
            # Convert magnetic variation (16-bit signed, negative = West)
            # Stored as: degrees * 65536 / 360
            # So: degrees = value * 360 / 65536
            if isinstance(mag_var_raw, int):
                # Handle as signed 16-bit
                if mag_var_raw >= 2**15:
                    mag_var_raw = mag_var_raw - 2**16
                mag_var = (float(mag_var_raw) * 360.0) / 65536.0
            else:
                mag_var = float(mag_var_raw) if mag_var_raw else 0.0
            
            # Debug: log heading conversion (only in debug mode)
            if not hasattr(self, '_heading_debug_logged'):
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Heading conversion: true={true_heading:.1f}°, mag_var={mag_var:.1f}°, magnetic={true_heading - mag_var:.1f}°")
                self._heading_debug_logged = True
            
            # Calculate magnetic heading: magnetic = true - variation
            # Note: West variation is negative, so subtracting it adds to the heading
            state.heading_deg = true_heading - mag_var
            
            # Normalize heading to 0-360
            while state.heading_deg < 0:
                state.heading_deg += 360.0
            while state.heading_deg >= 360.0:
                state.heading_deg -= 360.0
            
            # On ground: 1 = on ground (offset 0x0366)
            on_ground_raw = data[10]
            state.on_ground = (on_ground_raw & 1) != 0
            
            return state
            
        except FSUIPCException as e:
            # Connection lost - try to reconnect once
            self.connected = False
            self._cached_connection_status = False  # Update cache
            self._last_connection_check = time.time()
            if self.config.auto_reconnect:
                try:
                    if self.reconnect():
                        # Retry once after reconnection
                        return self.get_aircraft_state()
                except:
                    pass
            return None
        except Exception as e:
            # Other error
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error reading aircraft state: {e}")
            return None
    
    def _get_dev_state(self) -> AircraftState:
        """Get simulated aircraft state for DEV mode."""
        state = AircraftState()
        # Simulated position (somewhere over North America)
        state.lat = 40.7128
        state.lon = -74.0060
        state.alt_ft = 5000.0
        state.gs_kt = 150.0
        state.vs_fpm = 0.0
        state.heading_deg = 90.0
        state.on_ground = False
        return state


def get_aircraft_state(bridge: FSUIPCBridge) -> Optional[Dict]:
    """
    Get aircraft state as dictionary.
    
    This is the clean function interface specified in requirements.
    """
    state = bridge.get_aircraft_state()
    if state:
        return state.to_dict()
    return None
