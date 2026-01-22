"""Configuration management with persistence."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
import re

# Try to import field_validator (Pydantic v2), fallback to validator (Pydantic v1)
try:
    from pydantic import field_validator
except ImportError:
    from pydantic import validator as field_validator


class WeatherSourceConfig(BaseModel):
    """Configuration for a weather source."""
    enabled: bool = True
    source_type: str = "aviationweather"  # aviationweather, manual, etc.
    cache_seconds: int = Field(default=45, ge=0, le=300)
    metar_refresh_seconds: int = Field(default=60, ge=10, le=60, description="METAR refresh rate (minimum 10 seconds, max 60 seconds)")
    taf_refresh_seconds: int = Field(default=600, ge=1, le=600, description="TAF refresh rate (max 600 seconds = 10 minutes)")


class WeatherCombiningConfig(BaseModel):
    """Configuration for weather combining mode."""
    mode: str = Field(default="metar_only")
    taf_fallback_stale_seconds: int = Field(default=300, ge=0)
    
    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v):
        if v not in ["metar_only", "metar_taf_fallback", "metar_taf_assist"]:
            raise ValueError("mode must be one of: metar_only, metar_taf_fallback, metar_taf_assist")
        return v


class SmoothingConfig(BaseModel):
    """Configuration for weather smoothing."""
    max_wind_dir_change_deg: float = Field(default=5.0, ge=0.0, le=180.0)
    max_wind_speed_change_kt: float = Field(default=2.0, ge=0.0, le=50.0)
    max_qnh_change_hpa: float = Field(default=0.5, ge=0.0, le=10.0)
    max_visibility_change: float = Field(default=0.5, ge=0.0)
    cloud_change_threshold: float = Field(default=1000.0, ge=0.0)
    transition_mode: str = Field(default="time_based", description="step_limited or time_based")
    
    @field_validator('transition_mode')
    @classmethod
    def validate_transition_mode(cls, v):
        if v not in ["step_limited", "time_based"]:
            raise ValueError("transition_mode must be one of: step_limited, time_based")
        return v
    
    # Time-based transition parameters (used when transition_mode="time_based")
    transition_interval_seconds: float = Field(default=30.0, ge=10.0, le=300.0, description="Interval between transition steps (minimum 10 seconds, 30-60 seconds recommended)")
    visibility_step_m: float = Field(default=200.0, ge=50.0, le=1000.0, description="Visibility change per step in meters (e.g., 200m every 30-60s)")
    wind_speed_step_kt: float = Field(default=2.0, ge=0.5, le=10.0, description="Wind speed change per step in knots")
    wind_dir_step_deg: float = Field(default=5.0, ge=1.0, le=30.0, description="Wind direction change per step in degrees")
    qnh_step_hpa: float = Field(default=0.5, ge=0.1, le=2.0, description="QNH change per step in hPa")
    
    approach_freeze_alt_ft: float = Field(default=1000.0, ge=0.0)
    big_change_wind_deg: float = Field(default=30.0, ge=0.0)
    big_change_wind_speed_kt: float = Field(default=10.0, ge=0.0)
    big_change_qnh_hpa: float = Field(default=5.0, ge=0.0)


class StationSelectionConfig(BaseModel):
    """Configuration for station selection."""
    radius_nm: float = Field(default=50.0, ge=0.0, le=500.0)
    max_stations: int = Field(default=3, ge=1, le=10)
    fallback_to_global: bool = True


class ManualWeatherConfig(BaseModel):
    """Configuration for manual weather mode."""
    enabled: bool = False
    mode: str = Field(default="station")
    
    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v):
        if v not in ["station", "report"]:
            raise ValueError("mode must be one of: station, report")
        return v
    icao: Optional[str] = None
    raw_metar: Optional[str] = None
    raw_taf: Optional[str] = None
    freeze: bool = False


class FSUIPCConfig(BaseModel):
    """Configuration for FSUIPC connection."""
    enabled: bool = True
    dev_mode: bool = False
    auto_reconnect: bool = True
    reconnect_interval_seconds: float = Field(default=5.0, ge=1.0, le=60.0)


class WebUIConfig(BaseModel):
    """Configuration for web UI."""
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1024, le=65535)
    update_interval_seconds: float = Field(default=1.0, ge=0.1, le=10.0)


class AppConfig(BaseModel):
    """Main application configuration."""
    weather_source: WeatherSourceConfig = Field(default_factory=WeatherSourceConfig)
    weather_combining: WeatherCombiningConfig = Field(default_factory=WeatherCombiningConfig)
    smoothing: SmoothingConfig = Field(default_factory=SmoothingConfig)
    station_selection: StationSelectionConfig = Field(default_factory=StationSelectionConfig)
    manual_weather: ManualWeatherConfig = Field(default_factory=ManualWeatherConfig)
    fsuipc: FSUIPCConfig = Field(default_factory=FSUIPCConfig)
    web_ui: WebUIConfig = Field(default_factory=WebUIConfig)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "AppConfig":
        """Load configuration from file."""
        if config_path is None:
            config_path = Path.home() / ".fsweatherbridge" / "config.json"
        
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        if config_path.exists():
            with open(config_path, "r") as f:
                data = json.load(f)
            return cls(**data)
        else:
            # Create default config
            config = cls()
            config.save(config_path)
            return config

    def save(self, config_path: Optional[Path] = None) -> None:
        """Save configuration to file."""
        if config_path is None:
            config_path = Path.home() / ".fsweatherbridge" / "config.json"
        
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, "w") as f:
            json.dump(self.dict(), f, indent=2)

    def dict(self) -> Dict[str, Any]:
        """Convert to dictionary (Pydantic v1/v2 compatible)."""
        # Try Pydantic v2 method first, fallback to v1
        try:
            return {
                "weather_source": self.weather_source.model_dump(),
                "weather_combining": self.weather_combining.model_dump(),
                "smoothing": self.smoothing.model_dump(),
                "station_selection": self.station_selection.model_dump(),
                "manual_weather": self.manual_weather.model_dump(),
                "fsuipc": self.fsuipc.model_dump(),
                "web_ui": self.web_ui.model_dump(),
            }
        except AttributeError:
            # Pydantic v1
            return {
                "weather_source": self.weather_source.dict(),
                "weather_combining": self.weather_combining.dict(),
                "smoothing": self.smoothing.dict(),
                "station_selection": self.station_selection.dict(),
                "manual_weather": self.manual_weather.dict(),
                "fsuipc": self.fsuipc.dict(),
                "web_ui": self.web_ui.dict(),
            }
