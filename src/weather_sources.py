"""Weather source abstraction and implementations."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class WeatherSource(ABC):
    """Abstract base class for weather sources."""
    
    def __init__(self, cache_seconds: int = 45):
        """
        Initialize weather source.
        
        Args:
            cache_seconds: Cache duration in seconds
        """
        self.cache_seconds = cache_seconds
        self._metar_cache: Dict[str, tuple[str, float]] = {}  # icao -> (metar, timestamp)
        self._taf_cache: Dict[str, tuple[str, float]] = {}  # icao -> (taf, timestamp)
    
    def _is_cache_valid(self, timestamp: float) -> bool:
        """Check if cache entry is still valid."""
        return (time.time() - timestamp) < self.cache_seconds
    
    @abstractmethod
    async def fetch_metar(self, icaos: list[str]) -> dict[str, str]:
        """
        Fetch METAR reports for given ICAO codes.
        
        Args:
            icaos: List of ICAO codes
        
        Returns:
            Dictionary mapping ICAO codes to raw METAR strings
        """
        pass
    
    @abstractmethod
    async def fetch_taf(self, icaos: list[str]) -> dict[str, str]:
        """
        Fetch TAF reports for given ICAO codes.
        
        Args:
            icaos: List of ICAO codes
        
        Returns:
            Dictionary mapping ICAO codes to raw TAF strings
        """
        pass


class AviationWeatherSource(WeatherSource):
    """AviationWeather.gov Data API source."""
    
    BASE_URL = "https://aviationweather.gov/api/data"
    
    async def fetch_metar(self, icaos: list[str]) -> dict[str, str]:
        """Fetch METAR from AviationWeather.gov."""
        result: dict[str, str] = {}
        
        # Check cache first
        uncached_icaos = []
        for icao in icaos:
            icao_upper = icao.upper()
            if icao_upper in self._metar_cache:
                metar, timestamp = self._metar_cache[icao_upper]
                if self._is_cache_valid(timestamp):
                    result[icao_upper] = metar
                    continue
            uncached_icaos.append(icao_upper)
        
        if not uncached_icaos:
            return result
        
        # Fetch from API
        try:
            logger.info(f"Fetching METAR for stations: {', '.join(uncached_icaos)}")
            async with aiohttp.ClientSession() as session:
                # AviationWeather.gov API format
                icao_list = ",".join(uncached_icaos)
                url = f"{self.BASE_URL}/metar"
                params = {
                    "ids": icao_list,
                    "format": "raw",
                    "hours": "1",
                }
                
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        text = await response.text()
                        # Parse response - each line is a METAR
                        lines = text.strip().split("\n")
                        fetched_count = 0
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            
                            # Extract ICAO from METAR (first 4 chars after optional prefix)
                            parts = line.split()
                            if len(parts) >= 2:
                                # METAR format: METAR ICAO ...
                                icao_from_metar = parts[1] if parts[0].upper() == "METAR" else parts[0]
                                if len(icao_from_metar) == 4:
                                    icao_upper = icao_from_metar.upper()
                                    if icao_upper in uncached_icaos:
                                        result[icao_upper] = line
                                        self._metar_cache[icao_upper] = (line, time.time())
                                        fetched_count += 1
                                        logger.info(f"METAR fetched for {icao_upper}: {line[:80]}...")
                        logger.info(f"METAR fetch complete: {fetched_count}/{len(uncached_icaos)} stations")
                    else:
                        # Retry once on failure
                        await asyncio.sleep(1)
                        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as retry_response:
                            if retry_response.status == 200:
                                text = await retry_response.text()
                                lines = text.strip().split("\n")
                                for line in lines:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    parts = line.split()
                                    if len(parts) >= 2:
                                        icao_from_metar = parts[1] if parts[0].upper() == "METAR" else parts[0]
                                        if len(icao_from_metar) == 4:
                                            icao_upper = icao_from_metar.upper()
                                            if icao_upper in uncached_icaos:
                                                result[icao_upper] = line
                                                self._metar_cache[icao_upper] = (line, time.time())
        except Exception as e:
            # Log error but don't fail
            logger.error(f"Error fetching METAR: {e}", exc_info=True)
        
        return result
    
    async def fetch_taf(self, icaos: list[str]) -> dict[str, str]:
        """Fetch TAF from AviationWeather.gov."""
        result: dict[str, str] = {}
        
        # Check cache first
        uncached_icaos = []
        for icao in icaos:
            icao_upper = icao.upper()
            if icao_upper in self._taf_cache:
                taf, timestamp = self._taf_cache[icao_upper]
                if self._is_cache_valid(timestamp):
                    result[icao_upper] = taf
                    continue
            uncached_icaos.append(icao_upper)
        
        if not uncached_icaos:
            return result
        
        # Fetch from API
        try:
            logger.info(f"Fetching TAF for stations: {', '.join(uncached_icaos)}")
            async with aiohttp.ClientSession() as session:
                icao_list = ",".join(uncached_icaos)
                url = f"{self.BASE_URL}/taf"
                params = {
                    "ids": icao_list,
                    "format": "raw",
                    "hours": "6",
                }
                
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        text = await response.text()
                        lines = text.strip().split("\n")
                        fetched_count = 0
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            
                            # Extract ICAO from TAF
                            parts = line.split()
                            if len(parts) >= 2:
                                icao_from_taf = parts[1] if parts[0].upper() == "TAF" else parts[0]
                                if len(icao_from_taf) == 4:
                                    icao_upper = icao_from_taf.upper()
                                    if icao_upper in uncached_icaos:
                                        result[icao_upper] = line
                                        self._taf_cache[icao_upper] = (line, time.time())
                                        fetched_count += 1
                                        logger.info(f"TAF fetched for {icao_upper}: {line[:80]}...")
                        logger.info(f"TAF fetch complete: {fetched_count}/{len(uncached_icaos)} stations")
                    else:
                        # Retry once
                        await asyncio.sleep(1)
                        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as retry_response:
                            if retry_response.status == 200:
                                text = await retry_response.text()
                                lines = text.strip().split("\n")
                                for line in lines:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    parts = line.split()
                                    if len(parts) >= 2:
                                        icao_from_taf = parts[1] if parts[0].upper() == "TAF" else parts[0]
                                        if len(icao_from_taf) == 4:
                                            icao_upper = icao_from_taf.upper()
                                            if icao_upper in uncached_icaos:
                                                result[icao_upper] = line
                                                self._taf_cache[icao_upper] = (line, time.time())
        except Exception as e:
            logger.error(f"Error fetching TAF: {e}", exc_info=True)
        
        return result
