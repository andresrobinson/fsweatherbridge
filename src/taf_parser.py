"""TAF parser - minimal parsing for weather guidance."""

import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class TAFGroup:
    """Represents a TAF group (FM, TEMPO, etc.)."""
    
    def __init__(self, group_type: str, start_time: Optional[datetime], end_time: Optional[datetime]):
        """
        Initialize TAF group.
        
        Args:
            group_type: FM, TEMPO, PROB, etc.
            start_time: Group start time
            end_time: Group end time
        """
        self.group_type = group_type
        self.start_time = start_time
        self.end_time = end_time
        self.wind_dir_deg: Optional[int] = None
        self.wind_speed_kt: Optional[float] = None
        self.wind_gust_kt: Optional[float] = None
        self.visibility_nm: Optional[float] = None
        self.clouds: List[Dict] = []
        self.weather_tokens: List[str] = []
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "group_type": self.group_type,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "wind_dir_deg": self.wind_dir_deg,
            "wind_speed_kt": self.wind_speed_kt,
            "wind_gust_kt": self.wind_gust_kt,
            "visibility_nm": self.visibility_nm,
            "clouds": self.clouds,
            "weather_tokens": self.weather_tokens,
        }


class ParsedTAF:
    """Parsed TAF data."""
    
    def __init__(self, raw: str):
        self.raw = raw
        self.icao: Optional[str] = None
        self.issue_time: Optional[datetime] = None
        self.valid_from: Optional[datetime] = None
        self.valid_to: Optional[datetime] = None
        self.prevailing: TAFGroup = TAFGroup("PREVAILING", None, None)
        self.groups: List[TAFGroup] = []
        self.valid = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "raw": self.raw,
            "icao": self.icao,
            "issue_time": self.issue_time.isoformat() if self.issue_time else None,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "prevailing": self.prevailing.to_dict(),
            "groups": [g.to_dict() for g in self.groups],
            "valid": self.valid,
        }


def parse_taf_date(date_str: str, base_date: Optional[datetime] = None) -> Optional[datetime]:
    """Parse TAF date string (e.g., '311200Z')."""
    if not date_str or len(date_str) < 7:
        return None
    
    try:
        day = int(date_str[:2])
        hour = int(date_str[2:4])
        minute = int(date_str[4:6])
        
        if base_date is None:
            base_date = datetime.utcnow()
        
        # Handle month rollover
        result = base_date.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if result > base_date + timedelta(days=15):
            # Probably previous month
            if base_date.month == 1:
                result = result.replace(month=12, year=base_date.year - 1)
            else:
                result = result.replace(month=base_date.month - 1)
        elif result < base_date - timedelta(days=15):
            # Probably next month
            if base_date.month == 12:
                result = result.replace(month=1, year=base_date.year + 1)
            else:
                result = result.replace(month=base_date.month + 1)
        
        return result
    except (ValueError, AttributeError):
        return None


def parse_taf(raw: str) -> ParsedTAF:
    """
    Parse TAF string - minimal parser for weather guidance.
    
    This is NOT a full ICAO-compliant TAF parser.
    """
    taf = ParsedTAF(raw)
    
    if not raw or len(raw) < 10:
        return taf
    
    # Extract ICAO
    parts = raw.split()
    if len(parts) >= 2:
        if parts[0].upper() == "TAF" and len(parts) > 1:
            taf.icao = parts[1][:4].upper()
        elif len(parts[0]) == 4:
            taf.icao = parts[0].upper()
    
    # Parse issue time and valid period
    # Format: TAF ICAO DDhhmmZ DDhhmm/DDhhmmZ
    date_pattern = r'\b(\d{6})Z\b'
    date_matches = list(re.finditer(date_pattern, raw))
    
    if len(date_matches) >= 1:
        taf.issue_time = parse_taf_date(date_matches[0].group(1))
    
    if len(date_matches) >= 2:
        taf.valid_from = parse_taf_date(date_matches[1].group(1))
    
    if len(date_matches) >= 3:
        taf.valid_to = parse_taf_date(date_matches[2].group(1))
    elif len(date_matches) >= 2:
        # Valid period might be in format DDhhmm/DDhhmmZ
        period_pattern = r'\b(\d{6})/(\d{6})Z\b'
        period_match = re.search(period_pattern, raw)
        if period_match:
            taf.valid_from = parse_taf_date(period_match.group(1))
            taf.valid_to = parse_taf_date(period_match.group(2))
    
    # Parse prevailing conditions (before first FM)
    # Extract wind, visibility, clouds from main body
    wind_pattern = r'\b(\d{3}|VRB)(\d{2,3})(G(\d{2,3}))?KT\b'
    wind_match = re.search(wind_pattern, raw)
    if wind_match:
        dir_str = wind_match.group(1)
        speed_str = wind_match.group(2)
        gust_str = wind_match.group(4)
        
        if dir_str != "VRB":
            taf.prevailing.wind_dir_deg = int(dir_str)
        taf.prevailing.wind_speed_kt = float(speed_str)
        if gust_str:
            taf.prevailing.wind_gust_kt = float(gust_str)
    
    # Parse FM groups (forecast changes)
    fm_pattern = r'\bFM(\d{6})Z\b'
    fm_matches = list(re.finditer(fm_pattern, raw))
    
    for i, fm_match in enumerate(fm_matches):
        start_time = parse_taf_date(fm_match.group(1))
        
        # Find end time (next FM or end of TAF)
        if i + 1 < len(fm_matches):
            end_time = parse_taf_date(fm_matches[i + 1].group(1))
        else:
            end_time = taf.valid_to
        
        group = TAFGroup("FM", start_time, end_time)
        
        # Extract wind from this group
        # Find text between this FM and next
        start_pos = fm_match.end()
        if i + 1 < len(fm_matches):
            end_pos = fm_matches[i + 1].start()
        else:
            end_pos = len(raw)
        
        group_text = raw[start_pos:end_pos]
        
        group_wind_match = re.search(wind_pattern, group_text)
        if group_wind_match:
            dir_str = group_wind_match.group(1)
            speed_str = group_wind_match.group(2)
            gust_str = group_wind_match.group(4)
            
            if dir_str != "VRB":
                group.wind_dir_deg = int(dir_str)
            group.wind_speed_kt = float(speed_str)
            if gust_str:
                group.wind_gust_kt = float(gust_str)
        
        taf.groups.append(group)
    
    # Mark as valid if we got basic structure
    taf.valid = (
        taf.icao is not None and
        taf.valid_from is not None
    )
    
    return taf
