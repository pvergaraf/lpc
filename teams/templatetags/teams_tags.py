from django import template
from datetime import datetime, timedelta, date

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

@register.filter
def calculate_age(birth_date):
    if not birth_date:
        return ''
    today = date.today()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    return f"{age} years old"

@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using bracket notation in templates."""
    if not dictionary:
        return None
    try:
        return dictionary.get(key)
    except (AttributeError, KeyError, TypeError):
        return None

@register.filter
def filter_by_team(queryset, team):
    return queryset.filter(team=team)

@register.filter
def add_minutes(time_str, minutes):
    """Add or subtract minutes from a time string."""
    try:
        # Parse the time string
        time_obj = datetime.strptime(time_str, "%H:%M")
        # Add the minutes (can be negative for subtraction)
        delta = timedelta(minutes=int(minutes))
        new_time = (datetime.combine(datetime.today(), time_obj.time()) + delta).time()
        return new_time
    except (ValueError, TypeError):
        return time_str

@register.filter
def length_active(queryset):
    """Count the number of active players in a queryset."""
    if not queryset:
        return 0
    return queryset.filter(teammemberprofile__active_player=True).count()

@register.filter
def format_match_time(time_obj):
    """Format match time, showing 'TBD' if not set."""
    if not time_obj:
        return "TBD"
    return time_obj.strftime('%I:%M %p')

@register.filter
def format_arrival_time(time_obj, minutes_before=45):
    """Format arrival time, showing 'TBD' if match time not set."""
    if not time_obj:
        return "TBD"
    arrival_time = datetime.combine(date.today(), time_obj) - timedelta(minutes=minutes_before)
    return arrival_time.strftime('%I:%M %p')

@register.filter
def format_field_number(field_number):
    """Format field number, showing 'TBD' if not set."""
    if not field_number:
        return "TBD"
    return str(field_number) 