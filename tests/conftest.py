"""
Storm Energy RTU Platform — pytest shared fixtures.
"""
import sys
import os

# Make the backend package importable from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
