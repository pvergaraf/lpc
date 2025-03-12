from django import template
from datetime import datetime, timedelta

register = template.Library()

@register.filter
def currency_no_decimals(value):
    try:
        return "{:,.0f}".format(float(value))
    except (ValueError, TypeError):
        return value

@register.filter
def country_flag(country_code):
    if not country_code:
        return ''
    # Convert country code to regional indicator symbols
    # Each regional indicator symbol is made up of the base (0x1F1E6-0x1F1FF)
    # plus the relative position in the alphabet (0-25)
    base = 0x1F1E6  # Regional Indicator Symbol Letter A
    try:
        char1, char2 = country_code.upper()
        return chr(base + ord(char1) - ord('A')) + chr(base + ord(char2) - ord('A'))
    except:
        return ''

@register.filter
def arrival_time(time_str, minutes_before):
    try:
        # Parse the time string
        time_obj = datetime.strptime(time_str, '%I:%M %p')
        # Subtract the minutes
        arrival_time = time_obj - timedelta(minutes=minutes_before)
        # Format back to string
        return arrival_time.strftime('%I:%M %p')
    except:
        return time_str 