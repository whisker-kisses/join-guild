import sys
import os

# Add the project root to the Python path so app.py and its dependencies can be found
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from app import app as application
