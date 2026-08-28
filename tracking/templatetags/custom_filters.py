from django import template

register = template.Library()

@register.filter
def subtract(value, arg):
    try:
        return value - arg
    except (TypeError, ValueError):
        return None

@register.filter
def sum_attribute(queryset, attr_name):
    try:
        return sum(getattr(obj, attr_name) for obj in queryset)
    except (TypeError, ValueError, AttributeError):
        return 0


@register.filter
def user_display(user):
    """Return a safe display name for an optional assigned user."""
    if not user:
        return 'Unassigned'
    return user.get_full_name().strip() or user.username
