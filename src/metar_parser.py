"""METAR parser - pragmatic parsing for weather injection."""

import re
from typing import Dict, List, Optional


class CloudLayer:
    """Represents a cloud layer."""
    
    def __init__(self, coverage: str, base_ft: int):
        """
        Initialize cloud layer.
        
        Args:
            coverage: FEW, SCT, BKN, OVC
            base_ft: Base altitude in feet
        """
        self.coverage = coverage.upper()
        self.base_ft = base_ft
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "coverage": self.coverage,
            "base_ft": self.base_ft,
        }


class ParsedMETAR:
    """Parsed METAR data."""
    
    def __init__(self, raw: str):
        self.raw = raw
        self.icao: Optional[str] = None
        self.wind_dir_deg: Optional[int] = None
        self.wind_speed_kt: Optional[float] = None
        self.wind_gust_kt: Optional[float] = None
        self.visibility_nm: Optional[float] = None
        self.temperature_c: Optional[float] = None
        self.dewpoint_c: Optional[float] = None
        self.qnh_hpa: Optional[float] = None
        self.altimeter_inhg: Optional[float] = None
        self.clouds: List[CloudLayer] = []
        self.weather_tokens: List[str] = []
        self.valid = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "raw": self.raw,
            "icao": self.icao,
            "wind_dir_deg": self.wind_dir_deg,
            "wind_speed_kt": self.wind_speed_kt,
            "wind_gust_kt": self.wind_gust_kt,
            "visibility_nm": self.visibility_nm,
            "temperature_c": self.temperature_c,
            "dewpoint_c": self.dewpoint_c,
            "qnh_hpa": self.qnh_hpa,
            "altimeter_inhg": self.altimeter_inhg,
            "clouds": [c.to_dict() for c in self.clouds],
            "weather_tokens": self.weather_tokens,
            "valid": self.valid,
        }


def parse_metar(raw: str) -> ParsedMETAR:
    """
    Parse METAR string.
    
    This is a pragmatic parser, not a full ICAO-compliant parser.
    """
    metar = ParsedMETAR(raw)
    
    if not raw or len(raw) < 10:
        return metar
    
    # Extract ICAO (usually first 4-letter code after METAR keyword)
    parts = raw.split()
    if len(parts) >= 2:
        # Check if first part is METAR
        if parts[0].upper() == "METAR" and len(parts) > 1:
            metar.icao = parts[1][:4].upper()
        elif len(parts[0]) == 4:
            metar.icao = parts[0].upper()
    
    # Wind: e.g., "12015KT", "12015G25KT", "VRB05KT", "00000KT"
    wind_pattern = r'\b(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT\b'
    wind_match = re.search(wind_pattern, raw)
    if wind_match:
        dir_str = wind_match.group(1)
        speed_str = wind_match.group(2)
        gust_str = wind_match.group(4)
        
        if dir_str == "VRB":
            metar.wind_dir_deg = None  # Variable
        else:
            metar.wind_dir_deg = int(dir_str)
        
        metar.wind_speed_kt = float(speed_str)
        
        if gust_str:
            metar.wind_gust_kt = float(gust_str)
    
    # Check for CAVOK (Ceiling And Visibility OK) - means visibility >= 10km, no clouds below 5000ft
    if "CAVOK" in raw.upper():
        # CAVOK means visibility >= 10km (>= 5.4nm), no significant weather, no clouds below 5000ft
        metar.visibility_nm = 10.0  # Set to 10nm (well above 10km threshold)
        # No clouds when CAVOK
        metar.clouds = []
    else:
        # Visibility: e.g., "10SM", "1/2SM", "9999" (meters), "M1/4SM", "8000" (meters)
        # Visibility appears after wind (which ends with KT) and before weather/clouds
        # First check for 4-digit meter visibility (e.g., "9999", "8000", "0400")
        # Pattern: after KT, look for 4-digit number (not a date, which would be followed by Z)
        vis_4digit_pattern = r'KT\s+(\d{4})(?:\s|$|[A-Z])'
        vis_4digit_match = re.search(vis_4digit_pattern, raw)
        if vis_4digit_match:
            # 4-digit value is always in meters (ICAO format)
            vis_m = float(vis_4digit_match.group(1))
            if vis_m >= 9999:
                # "9999" in METAR means "10km or more" (unlimited/good visibility)
                metar.visibility_nm = 10.0  # Set to 10nm (>= 10km)
            else:
                metar.visibility_nm = vis_m * 0.000539957  # meters to nm
        else:
            # Check for SM (statute miles) or fractional visibility
            # Pattern: number or fraction, optionally followed by SM, after KT
            vis_pattern = r'KT\s+(\d{1,2}|\d{1,2}/\d{1,2}|M\d{1,2}/\d{1,2})(SM)?(?:\s|$|[A-Z])'
            vis_match = re.search(vis_pattern, raw)
            if vis_match:
                vis_str = vis_match.group(1)
                unit = vis_match.group(2)
                
                if "/" in vis_str:
                    # Fractional visibility
                    if vis_str.startswith("M"):
                        # Less than
                        vis_str = vis_str[1:]
                    parts = vis_str.split("/")
                    if len(parts) == 2:
                        try:
                            num = float(parts[0])
                            den = float(parts[1])
                            if den == 0:
                                # Division by zero - invalid fraction, skip
                                vis_nm = None
                            else:
                                vis_nm = num / den
                        except (ValueError, ZeroDivisionError):
                            # Invalid fraction format or division by zero
                            vis_nm = None
                    else:
                        vis_nm = None
                else:
                    vis_nm = float(vis_str)
                    if not unit:  # Assume meters if no SM (shouldn't happen with this pattern, but just in case)
                        vis_nm = vis_nm * 0.000539957  # meters to nm
                
                if vis_nm is not None:
                    metar.visibility_nm = vis_nm
    
    # Temperature/Dewpoint: e.g., "12/08", "M05/M10"
    temp_pattern = r'\b(M?\d{2})/(M?\d{2})\b'
    temp_match = re.search(temp_pattern, raw)
    if temp_match:
        temp_str = temp_match.group(1)
        dew_str = temp_match.group(2)
        
        if temp_str.startswith("M"):
            metar.temperature_c = -float(temp_str[1:])
        else:
            metar.temperature_c = float(temp_str)
        
        if dew_str.startswith("M"):
            metar.dewpoint_c = -float(dew_str[1:])
        else:
            metar.dewpoint_c = float(dew_str)
    
    # Altimeter/QNH: e.g., "A2992" (inches), "Q1013" (hPa)
    alt_pattern = r'\bA(\d{4})\b'
    alt_match = re.search(alt_pattern, raw)
    if alt_match:
        alt_str = alt_match.group(1)
        # Convert inches Hg to hPa: inHg * 33.8639 = hPa
        inhg = float(alt_str) / 100.0
        metar.altimeter_inhg = inhg
        metar.qnh_hpa = inhg * 33.8639
    
    qnh_pattern = r'\bQ(\d{4})\b'
    qnh_match = re.search(qnh_pattern, raw)
    if qnh_match:
        qnh_str = qnh_match.group(1)
        metar.qnh_hpa = float(qnh_str)
        metar.altimeter_inhg = metar.qnh_hpa / 33.8639
    
    # Clouds: e.g., "FEW020", "SCT030", "BKN040", "OVC050", "VV008"
    cloud_pattern = r'\b(FEW|SCT|BKN|OVC|VV)(\d{3})(\w+)?\b'
    cloud_matches = re.finditer(cloud_pattern, raw)
    for match in cloud_matches:
        coverage = match.group(1)
        base_str = match.group(2)
        base_ft = int(base_str) * 100
        metar.clouds.append(CloudLayer(coverage, base_ft))
    
    # Weather tokens: e.g., "RA", "SN", "TS", "BR", "FG"
    # Note: + and - are intensity modifiers, not weather codes, so we don't include them in the pattern
    weather_pattern = r'\b(RA|SN|TS|BR|FG|DZ|PL|SG|GR|GS|UP|HZ|FU|VA|DU|SA|PO|SQ|FC|SS|DS|IC|PE|SH|BL|DR|FZ|MI|BC|PR|VC|RE)\b'
    weather_matches = re.finditer(weather_pattern, raw)
    for match in weather_matches:
        token = match.group(1)
        metar.weather_tokens.append(token)
    
    # Mark as valid if we got at least some data
    metar.valid = (
        metar.icao is not None and
        (metar.wind_dir_deg is not None or metar.wind_speed_kt is not None) and
        metar.qnh_hpa is not None
    )
    
    return metar
