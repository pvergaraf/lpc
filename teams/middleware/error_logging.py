import sys
import traceback
from django.template import TemplateDoesNotExist
from django.conf import settings
from ..utils.logging_utils import log_error

class ErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
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