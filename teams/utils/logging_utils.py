import logging
import json
from datetime import datetime
from typing import Any, Dict, Optional

from django.http import HttpRequest

logger = logging.getLogger('django')

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
        "file_type": getattr(file, 'content_type', 'Unknown'),
    }

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
    user = request.user
    
    log_data = {
        "asctime": datetime.now().isoformat(),
        "levelname": "ERROR",
        "user": user.email if user.is_authenticated else "anonymous",
        "ip": request.META.get('REMOTE_ADDR', 'Unknown'),
        "message": error_message,
        "request_id": request.META.get('HTTP_X_REQUEST_ID', ''),
        "path": request.path,
        "method": request.method,
        "details": {
            "error_type": error_type,
            "error_message": error_message,
        },
        "context": get_client_info(request)
    }

    if file_info:
        log_data["details"].update({"file_info": file_info})
    
    if extra_context:
        log_data["details"].update(extra_context)

    logger.error(json.dumps(log_data, indent=2))

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