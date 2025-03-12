import sys
import traceback
from django.template import TemplateDoesNotExist
from django.conf import settings
from ..utils.logging_utils import log_error
import uuid

class ErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate a unique ID for this request
        request._logging_id = str(uuid.uuid4())[:8]
        
        # If this is a registration request, log it
        if 'register' in request.path:
            log_error(
                request=request,
                error_message=f"Started {request.method} request to {request.path}",
                error_type="RegistrationDebug",
                extra_context={"method": request.method, "path": request.path}
            )

        try:
            response = self.get_response(request)
            return response
        except Exception as e:
            # Get the full traceback
            exc_info = sys.exc_info()
            stack_trace = ''.join(traceback.format_exception(*exc_info))
            
            # Extract relevant request data
            request_data = {
                "GET": dict(request.GET),
                "POST": dict(request.POST),
                "FILES": {k: v.name for k, v in request.FILES.items()} if request.FILES else {},
                "headers": dict(request.headers),
                "method": request.method,
                "path": request.path,
                "content_type": request.content_type,
                "session": dict(request.session) if hasattr(request, 'session') else {},
            }

            # Add template-specific context for template errors
            extra_context = {
                "traceback": stack_trace,
                "request_data": request_data,
                "error_class": e.__class__.__name__,
                "error_module": e.__class__.__module__,
            }

            if isinstance(e, TemplateDoesNotExist):
                extra_context.update({
                    "template_name": str(e),
                    "template_dirs": settings.TEMPLATES[0]['DIRS'],
                    "installed_apps": settings.INSTALLED_APPS,
                    "template_loaders": [
                        loader.__class__.__name__ 
                        for loader in getattr(request, '_template_loaders', [])
                    ],
                })
            
            # Log the error with full context
            log_error(
                request=request,
                error_message=str(e),
                error_type="TemplateError" if isinstance(e, TemplateDoesNotExist) else "ServerError",
                extra_context=extra_context
            )
            
            # Re-raise the exception to let Django handle it
            raise 

        # Log completion of registration requests
        if 'register' in request.path:
            log_error(
                request=request,
                error_message=f"Completed {request.method} request to {request.path} with status {response.status_code}",
                error_type="RegistrationDebug"
            )

        return response

    def process_exception(self, request, exception):
        log_error(
            request=request,
            error_message=str(exception),
            error_type="Error",
            extra_context={"exception_type": exception.__class__.__name__}
        )
        return None 