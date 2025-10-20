from django import template

register = template.Library()

@register.filter
def subtract(value, arg):
    """Subtract the arg from the value."""
    try:
        return value - arg
    except (ValueError, TypeError):
        return ''

@register.filter
def as_percentage(value, decimals=1):
    """Convert decimal to percentage with specified decimal places."""
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (ValueError, TypeError):
        return ''

@register.filter
def absolute(value):
    """Return the absolute value."""
    try:
        return abs(value)
    except (ValueError, TypeError):
        return value

@register.simple_tag
def calculate_efficiency_change(current, previous):
    """Calculate percentage change in efficiency."""
    try:
        if not previous:
            return "N/A"
        change = ((current - previous) / previous) * 100
        return f"{change:+.1f}%" # + sign for positive changes
    except (ValueError, TypeError, ZeroDivisionError):
        return "N/A"