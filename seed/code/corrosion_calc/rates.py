"""Formulas from KCR SOP-INS-020 (synthetic)."""


def corrosion_rate(t_prev: float, t_actual: float, years: float) -> float:
    """Short-term corrosion rate in mm/year."""
    if years <= 0:
        raise ValueError("years must be positive")
    return (t_prev - t_actual) / years


def remaining_life(t_actual: float, t_min: float, cr: float) -> float | None:
    """Remaining life in years; None means 'more than 20 years' (no measurable corrosion)."""
    if cr <= 0:
        return None
    return (t_actual - t_min) / cr


def next_inspection_years(rl: float | None) -> float:
    """Lesser of half the remaining life or 10 years."""
    if rl is None:
        return 10.0
    return min(rl / 2, 10.0)
