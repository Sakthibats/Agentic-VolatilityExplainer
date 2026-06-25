def iv_rank(current_iv: float, iv_52w_high: float, iv_52w_low: float) -> float:
    """Return IV rank (0–100) given current IV and 52-week range."""
    if iv_52w_high == iv_52w_low:
        return 0.0
    return (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100.0
