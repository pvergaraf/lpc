import logging
import json
from datetime import datetime, date
from typing import Any, Dict, Optional
from functools import wraps
import os
import sys
import traceback
import threading
from django.http import HttpRequest

# Configure logging
logger = logging.getLogger('django')
logger.setLevel(logging.INFO)

# Remove existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Create a file handler for JSON logs
file_handler = logging.FileHandler('app.log')
file_handler.setLevel(logging.INFO)
logger.addHandler(file_handler)

# Disable all other loggers
logging.getLogger('django.db.backends').disabled = True
logging.getLogger('django.template').disabled = True
logging.getLogger('django.utils.autoreload').disabled = True
logging.getLogger('django.request').disabled = True

# ANSI color codes
COLORS = {
    'HEADER': '\033[95m',     # Magenta
    'INFO': '\033[94m',       # Blue
    'SUCCESS': '\033[92m',    # Green
    'WARNING': '\033[93m',    # Yellow
    'ERROR': '\033[91m',      # Red
    'RESET': '\033[0m',       # Reset
    'BOLD': '\033[1m',        # Bold
    'DIM': '\033[2m',         # Dim
}

class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that can handle dates and other complex types."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return str(obj)

def get_client_info(request: HttpRequest) -> Dict[str, str]:
    """Extract client information from the request."""
    return {
        "browser": request.META.get('HTTP_USER_AGENT', 'Unknown'),
        "ip": request.META.get('REMOTE_ADDR', 'Unknown'),
        "platform": request.META.get('HTTP_SEC_CH_UA_PLATFORM', 'Unknown'),
        "device_type": "mobile" if request.META.get('HTTP_USER_AGENT', '').lower().find('mobile') > -1 else "desktop"
    }

def get_file_info(file) -> Dict[str, Any]:
    """Extract file information."""
    if not file:
        return {}
    
    return {
        "file_name": getattr(file, 'name', 'Unknown'),
        "file_size": f"{file.size / (1024 * 1024):.2f}MB" if hasattr(file, 'size') else 'Unknown',
        "file_type": os.path.splitext(file.name)[1].lower() if hasattr(file, 'name') else 'Unknown',
    }

def format_context(context: Dict) -> Dict:
    """Format and filter context data to be more concise."""
    if not context:
        return {}
    
    # If it's POST data, only include relevant fields
    if 'post_data' in context:
        filtered_data = {}
        relevant_fields = [
            'first_name', 'last_name', 'email', 'player_number',
            'position', 'level', 'rut', 'country', 'description'
        ]
        post_data = context['post_data']
        for field in relevant_fields:
            if field in post_data:
                filtered_data[field] = post_data[field]
        context = {'form_data': filtered_data}
    
    # Remove any None values
    return {k: v for k, v in context.items() if v is not None}

def get_request_info(request: Optional[HttpRequest]) -> Dict[str, Any]:
    """Extract useful information from the request object."""
    if not request:
        return {}

    info = {
        'method': request.method,
        'path': request.path,
        'user': str(request.user) if hasattr(request, 'user') and request.user.is_authenticated else 'anonymous',
        'ip': request.META.get('REMOTE_ADDR'),
        'user_agent': request.META.get('HTTP_USER_AGENT'),
        'referer': request.META.get('HTTP_REFERER'),
    }

    # Add request parameters
    if request.method == 'GET':
        info['query_params'] = dict(request.GET)
    elif request.method == 'POST':
        # Exclude sensitive data
        post_data = dict(request.POST)
        sensitive_fields = {'password', 'token', 'key', 'secret', 'credit_card'}
        info['post_data'] = {
            k: '******' if any(sensitive in k.lower() for sensitive in sensitive_fields)
            else v for k, v in post_data.items()
        }

    return info

def get_error_context(error: Optional[Exception] = None) -> Dict[str, Any]:
    """Get detailed error information if an exception occurred."""
    if not error:
        return {}

    return {
        'error_type': error.__class__.__name__,
        'error_message': str(error),
        'traceback': traceback.format_exc(),
        'module': error.__class__.__module__
    }

def format_value(value: Any, indent: int = 0) -> str:
    """Format a value for console output with proper indentation."""
    indent_str = "  " * indent
    
    if isinstance(value, dict):
        if not value:
            return "{}"
        formatted = "\n"
        for k, v in value.items():
            formatted += f"{indent_str}  {k}: {format_value(v, indent + 1)}\n"
        return formatted.rstrip()
    elif isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        formatted = "\n"
        for item in value:
            formatted += f"{indent_str}  - {format_value(item, indent + 1)}\n"
        return formatted.rstrip()
    else:
        return str(value)

def print_log(title: str, data: Dict[str, Any], log_type: str = 'INFO') -> None:
    """
    Print a formatted, colored log message to the console.
    
    Args:
        title: The title/header of the log message
        data: Dictionary of data to log
        log_type: Type of log (INFO, SUCCESS, WARNING, ERROR)
    """
    color = COLORS.get(log_type, COLORS['INFO'])
    separator = COLORS['HEADER'] + "=" * 80 + COLORS['RESET']
    
    # Get timestamp
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    
    print(f"\n{separator}")
    print(f"{color}{COLORS['BOLD']}=== {title} === {COLORS['DIM']}[{timestamp}]{COLORS['RESET']}")
    
    # Print each key-value pair with proper formatting
    for key, value in data.items():
        if key in ['request', 'context', 'code_location']:
            print(f"{color}>> {key}:{format_value(value, 1)}{COLORS['RESET']}")
        else:
            print(f"{color}>> {key}: {value}{COLORS['RESET']}")
    
    print(f"{color}=== END {title} ==={COLORS['RESET']}")
    print(f"{separator}")

def log_error(request: Optional[HttpRequest], error_message: str, error_type: str, extra_context: Optional[Dict] = None) -> None:
    """Log an error with request and context information."""
    # Prepare the log data
    log_data = {
        "message": error_message,
        "error_type": error_type,
        "environment": os.getenv('DJANGO_ENV', 'development'),
        "timestamp": datetime.now().isoformat()
    }
    
    # Add request information if available
    if request:
        log_data["request"] = get_request_info(request)
    
    # Add extra context if provided
    if extra_context:
        log_data["context"] = format_context(extra_context)
    
    # Add code location
    frame = traceback.extract_stack()[-2]  # Get the caller's frame
    log_data["code_location"] = {
        "file": frame.filename,
        "function": frame.name,
        "line": frame.lineno
    }
    
    # Determine log type based on error_type
    log_type = 'ERROR' if 'error' in error_type.lower() else 'INFO'
    if 'success' in error_type.lower():
        log_type = 'SUCCESS'
    elif 'warning' in error_type.lower():
        log_type = 'WARNING'
    
    # Print colorful console log
    print_log(error_type, log_data, log_type)
    
    # Log to file as JSON
    logger.info(json.dumps(log_data, cls=CustomJSONEncoder))

def log_upload_error(
    request: HttpRequest,
    file,
    error_message: str,
    upload_type: str,
    attempted_location: str,
    validation_errors: Optional[Dict] = None
) -> None:
    """
    Specific logging for file upload errors.
    """
    file_info = get_file_info(file)
    extra_context = {
        "upload_type": upload_type,
        "attempted_location": attempted_location,
        "validation_errors": validation_errors or {}
    }
    
    log_error(
        request=request,
        error_message=f"File upload failed: {error_message}",
        error_type="UploadError",
        extra_context=extra_context,
        file_info=file_info
    )