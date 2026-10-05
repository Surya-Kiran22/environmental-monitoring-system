import math
import secrets
from datetime import datetime


def new_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%y%m%d')}-{secrets.token_hex(3).upper()}"


def now() -> datetime:
    """Local wall-clock time (Asia/Kolkata deployments store naive local timestamps)."""
    return datetime.now().replace(microsecond=0)


def clean(obj):
    """Make numpy/pandas/datetime values JSON-safe recursively."""
    import numpy as np
    import pandas as pd
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return obj
