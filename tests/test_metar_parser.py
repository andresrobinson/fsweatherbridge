"""Tests for METAR parser."""

import unittest

from src.metar_parser import parse_metar


class TestMETARParser(unittest.TestCase):
    """Test METAR parser."""
    
    def test_parse_simple_metar(self):
        """Test parsing a simple METAR."""
        raw = "METAR KJFK 121200Z 12015KT 10SM FEW020 12/08 A2992"
        metar = parse_metar(raw)
        
        self.assertEqual(metar.icao, "KJFK")
        self.assertEqual(metar.wind_dir_deg, 120)
        self.assertEqual(metar.wind_speed_kt, 15.0)
        self.assertIsNone(metar.wind_gust_kt)
        self.assertAlmostEqual(metar.visibility_nm, 10.0, places=1)
        self.assertEqual(metar.temperature_c, 12.0)
        self.assertEqual(metar.dewpoint_c, 8.0)
        self.assertIsNotNone(metar.qnh_hpa)
        self.assertTrue(metar.valid)
    
    def test_parse_metar_with_gusts(self):
        """Test parsing METAR with wind gusts."""
        raw = "METAR KLAX 121200Z 09020G30KT 10SM SCT030 15/10 Q1013"
        metar = parse_metar(raw)
        
        self.assertEqual(metar.wind_dir_deg, 90)
        self.assertEqual(metar.wind_speed_kt, 20.0)
        self.assertEqual(metar.wind_gust_kt, 30.0)
        self.assertIsNotNone(metar.qnh_hpa)
    
    def test_parse_metar_clouds(self):
        """Test parsing METAR with clouds."""
        raw = "METAR KORD 121200Z 00000KT 10SM BKN040 OVC060 10/05 A2995"
        metar = parse_metar(raw)
        
        self.assertEqual(len(metar.clouds), 2)
        self.assertEqual(metar.clouds[0].coverage, "BKN")
        self.assertEqual(metar.clouds[0].base_ft, 4000)
        self.assertEqual(metar.clouds[1].coverage, "OVC")
        self.assertEqual(metar.clouds[1].base_ft, 6000)
    
    def test_parse_invalid_metar(self):
        """Test parsing invalid METAR."""
        raw = "INVALID METAR STRING"
        metar = parse_metar(raw)
        
        self.assertFalse(metar.valid)
