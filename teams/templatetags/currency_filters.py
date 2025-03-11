from django import template
from django.template.defaultfilters import floatformat

register = template.Library()

@register.filter
def currency_no_decimals(value):
    try:
        # Convert to integer (removing decimals)
        value = int(float(value))
        # Format with thousand separators
        return "{:,}".format(value)
    except (ValueError, TypeError):
        return value 