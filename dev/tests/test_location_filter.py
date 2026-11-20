import pytest
from src.scrapers.base import BaseScraper

class DummyScraper(BaseScraper):
    def fetch_jobs(self):
        return []

def test_location_filter_matching():
    scraper = DummyScraper("test")
    # Matches Bangalore / Bengaluru
    assert scraper.matches_preferred_location("Bengaluru, Karnataka, India") is True
    assert scraper.matches_preferred_location("Bangalore Urban") is True
    # Matches Kochi / Cochin
    assert scraper.matches_preferred_location("Kochi, Kerala") is True
    assert scraper.matches_preferred_location("Cochin Infopark") is True
    # Matches Kozhikode / Calicut / KKD
    assert scraper.matches_preferred_location("Kozhikode Cyberpark") is True
    assert scraper.matches_preferred_location("Calicut, India") is True
    assert scraper.matches_preferred_location("KKD Tech Park") is True
    # Matches TVM / Trivandrum
    assert scraper.matches_preferred_location("Technopark, Trivandrum") is True
    assert scraper.matches_preferred_location("Thiruvananthapuram, Kerala") is True
    assert scraper.matches_preferred_location("TVM, India") is True
    # Matches Remote India
    assert scraper.matches_preferred_location("Remote India") is True

    # Rejects other cities and overseas locations
    assert scraper.matches_preferred_location("Mumbai, Maharashtra") is False
    assert scraper.matches_preferred_location("Delhi, NCR") is False
    assert scraper.matches_preferred_location("London, United Kingdom") is False
    assert scraper.matches_preferred_location("San Francisco, CA") is False
    assert scraper.matches_preferred_location("Berlin, Germany") is False
    assert scraper.matches_preferred_location("Singapore") is False
    assert scraper.matches_preferred_location("Remote US") is False
    assert scraper.matches_preferred_location("US-Remote") is False
