"""Minimal timestamp dependency of the unchanged frozen PED runtime."""
from datetime import datetime,timezone

def iso(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('Explicit timezone required')
    return stamp.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
