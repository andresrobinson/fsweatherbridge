"""Weather smoothing engine for gradual transitions."""

from typing import Dict, Optional

from src.config import SmoothingConfig


class WeatherState:
    """Current weather state (last injected)."""
    
    def __init__(self):
        self.wind_dir_deg: Optional[float] = None
        self.wind_speed_kt: Optional[float] = None
        self.wind_gust_kt: Optional[float] = None
        self.visibility_nm: Optional[float] = None
        self.temperature_c: Optional[float] = None
        self.dewpoint_c: Optional[float] = None
        self.qnh_hpa: Optional[float] = None
        self.clouds: list = []
        self.weather_tokens: list[str] = []
        # Metadata about the smoothing operation
        self.is_big_change: bool = False
        self.is_very_big_change: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "wind_dir_deg": self.wind_dir_deg,
            "wind_speed_kt": self.wind_speed_kt,
            "wind_gust_kt": self.wind_gust_kt,
            "visibility_nm": self.visibility_nm,
            "temperature_c": self.temperature_c,
            "dewpoint_c": self.dewpoint_c,
            "qnh_hpa": self.qnh_hpa,
            "clouds": self.clouds,
            "weather_tokens": self.weather_tokens,
        }
    
    def from_dict(self, data: dict) -> None:
        """Load from dictionary."""
        self.wind_dir_deg = data.get("wind_dir_deg")
        self.wind_speed_kt = data.get("wind_speed_kt")
        self.wind_gust_kt = data.get("wind_gust_kt")
        self.visibility_nm = data.get("visibility_nm")
        self.temperature_c = data.get("temperature_c")
        self.dewpoint_c = data.get("dewpoint_c")
        self.qnh_hpa = data.get("qnh_hpa")
        self.clouds = data.get("clouds", [])
        self.weather_tokens = data.get("weather_tokens", [])


class WeatherSmoother:
    """Weather smoothing engine."""
    
    def __init__(self, config: SmoothingConfig):
        self.config = config
        self.current_state = WeatherState()
        self.frozen = False
        self.freeze_altitude_ft: Optional[float] = None
    
    def set_freeze_altitude(self, altitude_ft: float) -> None:
        """Set current altitude for freeze logic."""
        self.freeze_altitude_ft = altitude_ft
        self.frozen = (
            self.freeze_altitude_ft is not None and
            self.freeze_altitude_ft < self.config.approach_freeze_alt_ft
        )
    
    def smooth(
        self,
        target: Dict,
        aircraft_alt_ft: Optional[float] = None,
    ) -> WeatherState:
        """
        Smooth transition from current state to target.
        
        Args:
            target: Target weather dictionary
            aircraft_alt_ft: Current aircraft altitude (for freeze logic)
        
        Returns:
            Smoothed weather state
        """
        # Update freeze status
        if aircraft_alt_ft is not None:
            self.set_freeze_altitude(aircraft_alt_ft)
        
        # If frozen, check for big changes
        if self.frozen:
            # If current state has None values, always break freeze (first initialization)
            if (self.current_state.wind_dir_deg is None or 
                self.current_state.wind_speed_kt is None or 
                self.current_state.qnh_hpa is None):
                self.frozen = False
            elif self._is_big_change(target):
                # Break freeze on big change
                self.frozen = False
            else:
                # Stay frozen, return current state
                return self.current_state
        
        # Create smoothed state
        smoothed = WeatherState()
        
        # Detect if this is a big change - compare current smoothed state to target
        # This will be true at the start of a transition, but false once we're close to target
        is_big_change = self._is_big_change(target)
        
        # Check for very large changes that should transition almost instantly
        is_very_big_change = False
        if (self.current_state.wind_speed_kt is not None and target.get("wind_speed_kt") is not None):
            wind_diff = abs(target["wind_speed_kt"] - self.current_state.wind_speed_kt)
            if wind_diff > 20.0:  # Very large wind change (>20kt)
                is_very_big_change = True
        if (self.current_state.visibility_nm is not None and target.get("visibility_nm") is not None):
            vis_diff = abs(target["visibility_nm"] - self.current_state.visibility_nm)
            if vis_diff > 10.0:  # Very large visibility change (>10nm)
                is_very_big_change = True
        
        # Calculate effective smoothing limits based on transition mode
        if self.config.transition_mode == "time_based":
            # Time-based mode: use step sizes per transition interval
            # Example: visibility changes by 200m every 30-60 seconds
            # Convert visibility step from meters to nautical miles
            visibility_step_nm = self.config.visibility_step_m / 1852.0  # meters to nm
            
            wind_dir_limit = self.config.wind_dir_step_deg
            wind_speed_limit = self.config.wind_speed_step_kt
            qnh_limit = self.config.qnh_step_hpa
            visibility_limit = visibility_step_nm
            
            import logging
            logger = logging.getLogger(__name__)
            if is_very_big_change or is_big_change:
                logger.info(f"Time-based transition: wind={wind_speed_limit:.1f}kt, vis={self.config.visibility_step_m:.0f}m, dir={wind_dir_limit:.1f}° per {self.config.transition_interval_seconds:.0f}s interval")
        else:
            # Step-limited mode (original behavior)
            if is_very_big_change:
                # For very big changes, allow near-instant transitions (50x normal rate)
                wind_dir_limit = self.config.max_wind_dir_change_deg * 50.0
                wind_speed_limit = self.config.max_wind_speed_change_kt * 50.0
                qnh_limit = self.config.max_qnh_change_hpa * 50.0
                visibility_limit = self.config.max_visibility_change * 50.0
                
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Very large weather change detected - using near-instant smoothing: wind={wind_speed_limit:.1f}kt/cycle, vis={visibility_limit:.1f}nm/cycle")
            elif is_big_change:
                # For big changes, allow much faster transitions (10x normal rate)
                wind_dir_limit = self.config.max_wind_dir_change_deg * 10.0
                wind_speed_limit = self.config.max_wind_speed_change_kt * 10.0
                qnh_limit = self.config.max_qnh_change_hpa * 10.0
                visibility_limit = self.config.max_visibility_change * 10.0
                
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Big weather change detected - using faster smoothing: wind={wind_speed_limit:.1f}kt/cycle, vis={visibility_limit:.1f}nm/cycle")
            else:
                wind_dir_limit = self.config.max_wind_dir_change_deg
                wind_speed_limit = self.config.max_wind_speed_change_kt
                qnh_limit = self.config.max_qnh_change_hpa
                visibility_limit = self.config.max_visibility_change
        
        # Smooth wind direction
        smoothed.wind_dir_deg = self._smooth_wind_dir(
            self.current_state.wind_dir_deg,
            target.get("wind_dir_deg"),
            max_change=wind_dir_limit,
        )
        
        # Smooth wind speed
        smoothed.wind_speed_kt = self._smooth_value(
            self.current_state.wind_speed_kt,
            target.get("wind_speed_kt"),
            wind_speed_limit,
        )
        
        # Smooth wind gust
        smoothed.wind_gust_kt = self._smooth_value(
            self.current_state.wind_gust_kt,
            target.get("wind_gust_kt"),
            wind_speed_limit,
        )
        
        # Smooth QNH
        smoothed.qnh_hpa = self._smooth_value(
            self.current_state.qnh_hpa,
            target.get("qnh_hpa"),
            qnh_limit,
        )
        
        # Smooth visibility
        smoothed.visibility_nm = self._smooth_value(
            self.current_state.visibility_nm,
            target.get("visibility_nm"),
            visibility_limit,
        )
        
        # Temperature and dewpoint - no smoothing (instant)
        smoothed.temperature_c = target.get("temperature_c")
        smoothed.dewpoint_c = target.get("dewpoint_c")
        
        # Clouds - simple threshold-based smoothing
        smoothed.clouds = self._smooth_clouds(
            self.current_state.clouds,
            target.get("clouds", []),
        )
        
        # Weather tokens - instant (no smoothing)
        smoothed.weather_tokens = target.get("weather_tokens", [])
        
        # Check if we're still transitioning (comparing smoothed result to target)
        # Only mark as big change if we're still far from target
        still_transitioning_big = False
        still_transitioning_very_big = False
        
        if is_very_big_change:
            # Check if smoothed state is still far from target
            if (smoothed.wind_speed_kt is not None and target.get("wind_speed_kt") is not None):
                wind_diff = abs(target["wind_speed_kt"] - smoothed.wind_speed_kt)
                if wind_diff > 5.0:  # Still more than 5kt away
                    still_transitioning_very_big = True
            if (smoothed.visibility_nm is not None and target.get("visibility_nm") is not None):
                vis_diff = abs(target["visibility_nm"] - smoothed.visibility_nm)
                if vis_diff > 2.0:  # Still more than 2nm away
                    still_transitioning_very_big = True
            # If no wind/vis check passed, check if any other parameter is still far
            if not still_transitioning_very_big:
                if (smoothed.wind_dir_deg is not None and target.get("wind_dir_deg") is not None):
                    wind_dir_diff = abs(target["wind_dir_deg"] - smoothed.wind_dir_deg)
                    if wind_dir_diff > 180:
                        wind_dir_diff = 360 - wind_dir_diff
                    if wind_dir_diff > 30.0:  # Still more than 30° away
                        still_transitioning_very_big = True
        
        if is_big_change and not still_transitioning_very_big:
            # Check if smoothed state is still far from target
            if (smoothed.wind_speed_kt is not None and target.get("wind_speed_kt") is not None):
                wind_diff = abs(target["wind_speed_kt"] - smoothed.wind_speed_kt)
                if wind_diff > 3.0:  # Still more than 3kt away
                    still_transitioning_big = True
            if (smoothed.visibility_nm is not None and target.get("visibility_nm") is not None):
                vis_diff = abs(target["visibility_nm"] - smoothed.visibility_nm)
                if vis_diff > 1.0:  # Still more than 1nm away
                    still_transitioning_big = True
            # If no wind/vis check passed, check if any other parameter is still far
            if not still_transitioning_big:
                if (smoothed.wind_dir_deg is not None and target.get("wind_dir_deg") is not None):
                    wind_dir_diff = abs(target["wind_dir_deg"] - smoothed.wind_dir_deg)
                    if wind_dir_diff > 180:
                        wind_dir_diff = 360 - wind_dir_diff
                    if wind_dir_diff > 15.0:  # Still more than 15° away
                        still_transitioning_big = True
        
        # Store metadata about the change for injection logic
        # Only mark as big change if we're still transitioning
        smoothed.is_big_change = still_transitioning_big
        smoothed.is_very_big_change = still_transitioning_very_big
        
        # Update current state
        self.current_state = smoothed
        
        return smoothed
    
    def _smooth_wind_dir(
        self,
        current: Optional[float],
        target: Optional[float],
        max_change: Optional[float] = None,
    ) -> Optional[float]:
        """Smooth wind direction with wraparound handling."""
        if target is None:
            return current
        if current is None:
            return target
        
        # Use provided max_change or default from config
        if max_change is None:
            max_change = self.config.max_wind_dir_change_deg
        
        # Ensure target is a number (handle string conversion if needed)
        try:
            target = float(target)
        except (ValueError, TypeError):
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"_smooth_wind_dir: target is not a number: {target} (type: {type(target)})")
            return current
        
        # Ensure current is a number
        try:
            current = float(current)
        except (ValueError, TypeError):
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"_smooth_wind_dir: current is not a number: {current} (type: {type(current)})")
            return target
        
        # Handle wraparound (0-360 degrees)
        diff = target - current
        
        # Normalize to -180 to 180
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        
        # Apply max change limit
        if abs(diff) > max_change:
            diff = max_change if diff > 0 else -max_change
        
        # Apply change
        result = current + diff
        
        # Normalize to 0-360
        while result < 0:
            result += 360
        while result >= 360:
            result -= 360
        
        return result
    
    def _smooth_value(
        self,
        current: Optional[float],
        target: Optional[float],
        max_change: float,
    ) -> Optional[float]:
        """Smooth a numeric value."""
        import logging
        logger = logging.getLogger(__name__)
        
        if target is None:
            return current
        if current is None:
            # First time - return target directly
            return target
        
        # Ensure target is a number (handle string conversion if needed)
        try:
            target_float = float(target)
        except (ValueError, TypeError) as e:
            logger.warning(f"_smooth_value: target is not a number: {target} (type: {type(target)}), error: {e}")
            return current
        
        # Ensure current is a number
        try:
            current_float = float(current)
        except (ValueError, TypeError) as e:
            logger.warning(f"_smooth_value: current is not a number: {current} (type: {type(current)}), error: {e}")
            return target_float
        
        diff = target_float - current_float
        
        if abs(diff) > max_change:
            diff = max_change if diff > 0 else -max_change
        
        result = current_float + diff
        
        if result is None:
            logger.error(f"_smooth_value: result is None! current={current_float}, target={target_float}, diff={diff}, max_change={max_change}")
        
        return result
    
    def _smooth_clouds(
        self,
        current: list,
        target: list,
    ) -> list:
        """Smooth cloud layers (simplified)."""
        # For now, just use target clouds
        # More sophisticated smoothing could be added later
        return target.copy() if target else current.copy()
    
    def _is_big_change(self, target: Dict) -> bool:
        """Check if target represents a big change that should break freeze or use faster smoothing."""
        # If current state has None values, it's a big change (initialization)
        if (self.current_state.wind_dir_deg is None or 
            self.current_state.wind_speed_kt is None or 
            self.current_state.qnh_hpa is None):
            return True
        
        big_change_detected = False
        
        # Check wind direction change
        if self.current_state.wind_dir_deg is not None and target.get("wind_dir_deg") is not None:
            diff = abs(target["wind_dir_deg"] - self.current_state.wind_dir_deg)
            if diff > 180:
                diff = 360 - diff
            if diff > self.config.big_change_wind_deg:
                big_change_detected = True
        
        # Check wind speed change
        if self.current_state.wind_speed_kt is not None and target.get("wind_speed_kt") is not None:
            diff = abs(target["wind_speed_kt"] - self.current_state.wind_speed_kt)
            if diff > self.config.big_change_wind_speed_kt:
                big_change_detected = True
        
        # Check QNH change
        if self.current_state.qnh_hpa is not None and target.get("qnh_hpa") is not None:
            diff = abs(target["qnh_hpa"] - self.current_state.qnh_hpa)
            if diff > self.config.big_change_qnh_hpa:
                big_change_detected = True
        
        # Check visibility change (big change if visibility changes by more than 5nm or goes from low to high)
        if self.current_state.visibility_nm is not None and target.get("visibility_nm") is not None:
            current_vis = self.current_state.visibility_nm
            target_vis = target["visibility_nm"]
            # Big change if visibility changes by more than 5nm, or goes from <1nm to >5nm (or vice versa)
            if abs(target_vis - current_vis) > 5.0:
                big_change_detected = True
            elif (current_vis < 1.0 and target_vis > 5.0) or (current_vis > 5.0 and target_vis < 1.0):
                big_change_detected = True
        
        # Check cloud coverage change (big change if going from overcast to clear or vice versa)
        current_has_clouds = len(self.current_state.clouds) > 0
        target_has_clouds = len(target.get("clouds", [])) > 0
        if current_has_clouds != target_has_clouds:
            # Check if it's a significant cloud change (e.g., OVC to SKC)
            if current_has_clouds:
                current_max_coverage = max((c.get('coverage', '') for c in self.current_state.clouds if isinstance(c, dict)), default='')
                if current_max_coverage in ['OVC', 'BKN']:
                    big_change_detected = True
            elif target_has_clouds:
                target_max_coverage = max((c.get('coverage', '') for c in target.get("clouds", []) if isinstance(c, dict)), default='')
                if target_max_coverage in ['OVC', 'BKN']:
                    big_change_detected = True
        
        return big_change_detected
