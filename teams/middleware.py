import logging
import uuid

class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger('teams')

    def __call__(self, request):
        # Generate a unique request ID
        request.id = str(uuid.uuid4())

        # Add custom context for logging
        extra = {
            'request_id': request.id,
            'ip': self.get_client_ip(request),
            'user': str(request.user) if hasattr(request, 'user') and request.user.is_authenticated else 'anonymous',
            'path': request.path,
            'method': request.method,
        }

        # Log the request
        self.logger.info(f"Request {request.method} {request.path}", extra=extra)

        response = self.get_response(request)

        # Log the response
        extra['status_code'] = response.status_code
        self.logger.info(f"Response {response.status_code}", extra=extra)

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR') 