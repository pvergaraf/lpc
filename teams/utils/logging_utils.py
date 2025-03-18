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

def log_error(
    request: Optional[HttpRequest],
    error_message: str,
    error_type: str,
    extra_context: Optional[Dict] = None,
    error: Optional[Exception] = None,
    level: str = 'error'
) -> None:
    """
    Enhanced error logging with detailed context.
    """
    try:
        # Base log data
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': level,
            'message': error_message,
            'error_type': error_type,
            'environment': os.getenv('DJANGO_ENV', 'development'),
            'process_id': os.getpid(),
            'thread_id': threading.get_ident(),
        }

        # Add request information
        if request:
            log_data['request'] = get_request_info(request)

        # Add error information if available
        if error:
            log_data['error'] = get_error_context(error)

        # Add any extra context
        if extra_context:
            log_data['context'] = extra_context

        # Add code location
        frame = sys._getframe(1)
        log_data['code_location'] = {
            'file': frame.f_code.co_filename,
            'function': frame.f_code.co_name,
            'line': frame.f_lineno
        }

        # Convert to JSON string
        log_message = json.dumps(log_data, cls=CustomJSONEncoder)

        # Log at appropriate level
        log_method = getattr(logger, level.lower(), logger.error)
        log_method(log_message)

    except Exception as e:
        # Fallback logging if something goes wrong
        logger.error(f"Error in logging: {str(e)}")
        logger.error(f"Original message: {error_message}")
        logger.error(f"Original context: {extra_context}")

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