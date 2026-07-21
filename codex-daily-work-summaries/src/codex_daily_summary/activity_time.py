def format_active_duration(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    hour_label = "hour" if hours == 1 else "hours"
    minute_label = "minute" if minutes == 1 else "minutes"
    total_label = "minute" if total_minutes == 1 else "minutes"
    return f"{hours} {hour_label} {minutes} {minute_label} ({total_minutes} {total_label})"
