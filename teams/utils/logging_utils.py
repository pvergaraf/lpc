import logging
import json
from datetime import datetime, date
from typing import Any, Dict, Optional
from functools import wraps
import os

from django.http import HttpRequest

# Disable all other loggers
logging.getLogger('django.db.backends').disabled = True
logging.getLogger('django.template').disabled = True
logging.getLogger('django.utils.autoreload').disabled = True
logging.getLogger('django.request').disabled = True

logger = logging.getLogger('django')

# ANSI color codes
COLORS = {
    'BLUE': '\033[94m',
    'GREEN': '\033[92m',
    'YELLOW': '\033[93m',
    'RED': '\033[91m',
    'MAGENTA': '\033[95m',
    'CYAN': '\033[96m',
    'ENDC': '\033[0m',  # End color
    'BOLD': '\033[1m',
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

def log_error(
    request: HttpRequest,
    error_message: str,
    error_type: str,
    extra_context: Optional[Dict] = None,
    file_info: Optional[Dict] = None
) -> None:
    """
    Enhanced error logging with detailed context.
    """
    # Only log if it's a registration-related message or an actual error
    if not ('Registration' in error_type or error_type.endswith('Error')):
        return

    # Get request ID or create one
    request_id = getattr(request, '_logging_id', None) if request else None
    
    # Format the log message with colors based on error_type
    if error_type == "RegistrationDebug":
        color = COLORS['CYAN']
        prefix = "🔍"
    elif error_type == "RegistrationError":
        color = COLORS['RED']
        prefix = "❌"
    elif "Registration" in error_type:
        color = COLORS['YELLOW']
        prefix = "⚠️"
    else:
        color = COLORS['RED']
        prefix = "❌"

    # Format the message
    if request_id:
        formatted_message = f"{color}{prefix} [{request_id}] {error_message}"
    else:
        formatted_message = f"{color}{prefix} {error_message}"

    # Add context if available, but filter and format it first
    if extra_context:
        formatted_context = format_context(extra_context)
        if formatted_context:
            context_str = json.dumps(formatted_context, cls=CustomJSONEncoder)
            formatted_message += f"\n  {context_str}"

    formatted_message += f"{COLORS['ENDC']}"
    logger.error(formatted_message)

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