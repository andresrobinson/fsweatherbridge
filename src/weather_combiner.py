"""Weather combining logic for METAR and TAF."""

from datetime import datetime
from typing import Dict, Optional

from src.config import WeatherCombiningConfig
from src.metar_parser import ParsedMETAR
from src.taf_parser import ParsedTAF


class CombinedWeather:
    """Combined weather data from METAR and TAF."""
    
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
        self.source: str = "unknown"
        self.metar_used: bool = False
        self.taf_used: bool = False
    
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
            "source": self.source,
            "metar_used": self.metar_used,
            "taf_used": self.taf_used,
        }


def combine_weather(
    metar: Optional[ParsedMETAR],
    taf: Optional[ParsedTAF],
    config: WeatherCombiningConfig,
    metar_age_seconds: Optional[float] = None,
) -> CombinedWeather:
    """
    Combine METAR and TAF according to combining mode.
    
    Args:
        metar: Parsed METAR (can be None)
        taf: Parsed TAF (can be None)
        config: Combining configuration
        metar_age_seconds: Age of METAR in seconds (for staleness check)
    
    Returns:
        Combined weather data
    """
    combined = CombinedWeather()
    
    if config.mode == "metar_only":
        # Use METAR only, ignore TAF
        if metar and metar.valid:
            _apply_metar(combined, metar)
            combined.source = "metar_only"
            combined.metar_used = True
        else:
            # No valid METAR
            combined.source = "none"
    
    elif config.mode == "metar_taf_fallback":
        # Use METAR if available and fresh, otherwise TAF
        metar_stale = (
            metar_age_seconds is not None and
            metar_age_seconds > config.taf_fallback_stale_seconds
        )
        
        if metar and metar.valid and not metar_stale:
            _apply_metar(combined, metar)
            combined.source = "metar"
            combined.metar_used = True
        elif taf and taf.valid:
            # Use TAF prevailing conditions
            _apply_taf_prevailing(combined, taf)
            combined.source = "taf_fallback"
            combined.taf_used = True
        elif metar and metar.valid:
            # Use stale METAR as last resort
            _apply_metar(combined, metar)
            combined.source = "metar_stale"
            combined.metar_used = True
        else:
            combined.source = "none"
    
    elif config.mode == "metar_taf_assist":
        # METAR defines current, TAF guides smoothing
        if metar and metar.valid:
            _apply_metar(combined, metar)
            combined.source = "metar"
            combined.metar_used = True
            
            # TAF is available for smoothing guidance but doesn't override
            if taf and taf.valid:
                combined.taf_used = True
        else:
            # No METAR, fallback to TAF
            if taf and taf.valid:
                _apply_taf_prevailing(combined, taf)
                combined.source = "taf_fallback"
                combined.taf_used = True
            else:
                combined.source = "none"
    
    return combined


def _apply_metar(combined: CombinedWeather, metar: ParsedMETAR) -> None:
    """Apply METAR data to combined weather."""
    combined.wind_dir_deg = float(metar.wind_dir_deg) if metar.wind_dir_deg is not None else None
    combined.wind_speed_kt = metar.wind_speed_kt
    combined.wind_gust_kt = metar.wind_gust_kt
    combined.visibility_nm = metar.visibility_nm
    combined.temperature_c = metar.temperature_c
    combined.dewpoint_c = metar.dewpoint_c
    combined.qnh_hpa = metar.qnh_hpa
    combined.clouds = [c.to_dict() for c in metar.clouds]
    combined.weather_tokens = metar.weather_tokens.copy()


def _apply_taf_prevailing(combined: CombinedWeather, taf: ParsedTAF) -> None:
    """Apply TAF prevailing conditions to combined weather."""
    if taf.prevailing.wind_dir_deg is not None:
        combined.wind_dir_deg = float(taf.prevailing.wind_dir_deg)
    combined.wind_speed_kt = taf.prevailing.wind_speed_kt
    combined.wind_gust_kt = taf.prevailing.wind_gust_kt
    combined.visibility_nm = taf.prevailing.visibility_nm
    combined.clouds = taf.prevailing.clouds.copy()
    combined.weather_tokens = taf.prevailing.weather_tokens.copy()
