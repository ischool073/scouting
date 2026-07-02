def percent_complete(completed, total):
    """Return the percentage of requirements completed, rounded to 1 decimal place."""
    if total <= 0:
        raise ValueError("total must be greater than 0")
    if completed < 0 or completed > total:
        raise ValueError("completed must be between 0 and total")
    return round((completed / total) * 100, 1)


def is_earned(completed, total):
    """Return True if all requirements for the badge have been completed."""
    return percent_complete(completed, total) >= 100.0
