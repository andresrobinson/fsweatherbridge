# FSUIPC Offsets Reference

This document provides detailed information about all FSUIPC offsets used by FSX Weather Bridge.

## Overview

FSX Weather Bridge uses FSUIPC offsets to:
1. **Read** aircraft position and state data
2. **Write** weather data (METAR strings) to FSX

All offsets are documented according to the FSUIPC4 SDK documentation.

---

## Reading Offsets (Aircraft State)

### Position Data

#### Latitude (0x0560, 0x0564)

- **Offset**: 0x0560 (low 32 bits), 0x0564 (high 32 bits)
- **Size**: 8 bytes total (64-bit signed integer)
- **Format**: `degrees * 2^32 / 360`
- **Type**: 
  - 0x0560: Unsigned 32-bit (low)
  - 0x0564: Signed 32-bit (high)
- **Units**: Degrees (decimal)
- **Range**: -90.0 to +90.0 degrees

**Reading Code**:
```python
lat_low = read_unsigned_32(0x0560)
lat_high = read_signed_32(0x0564)
latitude = ((lat_high << 32) + lat_low) * 360.0 / (2**32)
```

#### Longitude (0x0568, 0x056C)

- **Offset**: 0x0568 (low 32 bits), 0x056C (high 32 bits)
- **Size**: 8 bytes total (64-bit signed integer)
- **Format**: `degrees * 2^32 / 360`
- **Type**: 
  - 0x0568: Unsigned 32-bit (low)
  - 0x056C: Signed 32-bit (high)
- **Units**: Degrees (decimal)
- **Range**: -180.0 to +180.0 degrees

**Reading Code**:
```python
lon_low = read_unsigned_32(0x0568)
lon_high = read_signed_32(0x056C)
longitude = ((lon_high << 32) + lon_low) * 360.0 / (2**32)
```

#### Altitude (0x0570, 0x0574)

- **Offset**: 0x0570 (low 32 bits), 0x0574 (high 32 bits)
- **Size**: 8 bytes total (64-bit signed integer)
- **Format**: 
  - High 32 bits (0x0574): Integer metres (signed)
  - Low 32 bits (0x0570): Fractional metres (unsigned)
- **Type**: 
  - 0x0570: Unsigned 32-bit (fractional)
  - 0x0574: Signed 32-bit (integer)
- **Units**: Metres (converted to feet for display)
- **Range**: -32,768 to +32,767 metres (integer part)

**Reading Code**:
```python
alt_low = read_unsigned_32(0x0570)  # Fractional metres
alt_high = read_signed_32(0x0574)   # Integer metres
altitude_m = alt_high + (alt_low / (2**32))
altitude_ft = altitude_m * 3.28084  # Convert to feet
```

### Motion Data

#### Ground Speed (0x02B4)

- **Offset**: 0x02B4
- **Size**: 4 bytes
- **Format**: `metres/second * 65536`
- **Type**: Unsigned 32-bit
- **Units**: Metres per second (converted to knots)
- **Range**: 0 to 655.35 m/s (theoretical max)

**Reading Code**:
```python
gs_raw = read_unsigned_32(0x02B4)
gs_mps = gs_raw / 65536.0
gs_kt = gs_mps * 1.94384  # Convert to knots
```

#### Vertical Speed (0x02B8)

- **Offset**: 0x02B8
- **Size**: 4 bytes
- **Format**: `feet/minute * 256`
- **Type**: Signed 32-bit
- **Units**: Feet per minute
- **Range**: -8,388,608 to +8,388,607 ft/min

**Reading Code**:
```python
vs_raw = read_signed_32(0x02B8)
vs_fpm = vs_raw / 256.0
```

#### True Heading (0x0580)

- **Offset**: 0x0580
- **Size**: 4 bytes
- **Format**: `degrees * 2^32 / 360`
- **Type**: Unsigned 32-bit
- **Units**: Degrees
- **Range**: 0.0 to 360.0 degrees

**Reading Code**:
```python
heading_raw = read_unsigned_32(0x0580)
heading_deg = (heading_raw * 360.0) / (2**32)
# Normalize to 0-360
while heading_deg < 0:
    heading_deg += 360
while heading_deg >= 360:
    heading_deg -= 360
```

#### Magnetic Variation (0x02A0)

- **Offset**: 0x02A0
- **Size**: 2 bytes
- **Format**: Degrees (signed)
- **Type**: Signed 16-bit
- **Units**: Degrees
- **Range**: -180 to +180 degrees
- **Note**: Negative = West variation, Positive = East variation

**Reading Code**:
```python
mag_var = read_signed_16(0x02A0)
# Negative = West, Positive = East
```

### Status Data

#### On Ground Flag (0x0366)

- **Offset**: 0x0366
- **Size**: 2 bytes
- **Format**: 1 = on ground, 0 = in air
- **Type**: Unsigned 16-bit
- **Units**: Boolean flag
- **Range**: 0 or 1

**Reading Code**:
```python
on_ground_raw = read_unsigned_16(0x0366)
on_ground = (on_ground_raw == 1)
```

---

## Writing Offsets (Weather Injection)

### Weather METAR String (0xB000)

- **Offset**: 0xB000
- **Size**: 256 bytes (maximum)
- **Format**: Null-terminated string (METAR format)
- **Type**: String (char array)
- **Purpose**: Inject weather into FSX via METAR string

**METAR Format**:
```
METAR ICAO YYMMDDHHMMZ WIND VIS TEMP/DEW QNH CLOUDS WX
```

**Example**:
```
METAR KJFK 191200Z 12015KT 10SM OVC030 15/10 Q1013
```

**Writing Code**:
```python
metar_string = "METAR KJFK 191200Z 12015KT 10SM OVC030 15/10 Q1013"
metar_bytes = metar_string.encode('utf-8')[:255]  # Max 255 bytes + null terminator
# Ensure null termination
if len(metar_bytes) < 255:
    metar_bytes += b'\x00'
write_bytes(0xB000, metar_bytes)
```

**Important Notes**:
- Maximum length: 255 characters (plus null terminator = 256 bytes total)
- Must be null-terminated
- FSUIPC forwards this to SimConnect, which applies the weather
- Station-based injection: Use actual ICAO code (e.g., "KJFK")
- Global injection: Use "GLOB" as ICAO code

---

## Offset Summary Table

| Offset | Size | Type | Direction | Description |
|--------|------|------|-----------|-------------|
| 0x0560 | 4 bytes | Unsigned 32-bit | Read | Latitude (low) |
| 0x0564 | 4 bytes | Signed 32-bit | Read | Latitude (high) |
| 0x0568 | 4 bytes | Unsigned 32-bit | Read | Longitude (low) |
| 0x056C | 4 bytes | Signed 32-bit | Read | Longitude (high) |
| 0x0570 | 4 bytes | Unsigned 32-bit | Read | Altitude (fractional) |
| 0x0574 | 4 bytes | Signed 32-bit | Read | Altitude (integer) |
| 0x02B4 | 4 bytes | Unsigned 32-bit | Read | Ground speed |
| 0x02B8 | 4 bytes | Signed 32-bit | Read | Vertical speed |
| 0x0580 | 4 bytes | Unsigned 32-bit | Read | True heading |
| 0x02A0 | 2 bytes | Signed 16-bit | Read | Magnetic variation |
| 0x0366 | 2 bytes | Unsigned 16-bit | Read | On ground flag |
| 0xB000 | 256 bytes | String | Write | METAR weather string |

---

## Data Type Abbreviations

When using the `fsuipc` library's `prepare_data()` method, use these type codes:

- **`"u"`**: Unsigned 32-bit integer
- **`"d"`**: Signed 32-bit integer
- **`"h"`**: Unsigned 16-bit integer
- **`"H"`**: Signed 16-bit integer
- **`"b"`**: Byte array (for strings)

**Example**:
```python
prepared = fsuipc.prepare_data([
    (0x560, "u"),  # Latitude low (unsigned 32-bit)
    (0x564, "d"),  # Latitude high (signed 32-bit)
    (0x568, "u"),  # Longitude low (unsigned 32-bit)
    (0x56C, "d"),  # Longitude high (signed 32-bit)
    (0x570, "u"),  # Altitude low (unsigned 32-bit)
    (0x574, "d"),  # Altitude high (signed 32-bit)
    (0x2B4, "u"),  # Ground speed (unsigned 32-bit)
    (0x2B8, "d"),  # Vertical speed (signed 32-bit)
    (0x580, "u"),  # Heading (unsigned 32-bit)
    (0x2A0, "h"),  # Magnetic variation (signed 16-bit)
    (0x366, "H"),  # On ground (unsigned 16-bit)
], True)

data = prepared.read()
```

---

## References

- **FSUIPC4 SDK Documentation**: Available from Pete Dowson's website
- **FSUIPC Python Library**: [https://github.com/tjensen/fsuipc](https://github.com/tjensen/fsuipc)
- **FSUIPC Website**: http://www.fsuipc.com/

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-19
