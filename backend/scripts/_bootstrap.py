"""Put the backend dir on sys.path so scripts can import `app` and `ingest`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
