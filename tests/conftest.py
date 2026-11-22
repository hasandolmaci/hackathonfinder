"""Tests never use the online geocoder unless they mock it themselves."""
import os

os.environ["HF_GEOCODE_ONLINE"] = "0"
