"""
Custom middleware for XATSimplified.
"""
import logging

logger = logging.getLogger(__name__)


class CSRFExemptAPIMiddleware:
    """
    Middleware to exempt CSRF validation for API endpoints.
    This is needed for external clients (like pcc) that use API key authentication
    instead of session-based authentication.
    """

    EXEMPT_PATHS = [
        '/v1/',  # pcc-compatible endpoints
        '/api/v1/metrics/',  # Metrics upload
        '/api/v1/register/',  # pcc registration
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Log all requests
        logger.warning(f"CSRFExemptAPIMiddleware __call__: path={request.path}")

        # Check if path should be exempt from CSRF
        for path in self.EXEMPT_PATHS:
            if request.path.startswith(path):
                logger.warning(f"CSRFExemptAPIMiddleware: Exempting CSRF for path {request.path}")
                setattr(request, '_dont_enforce_csrf_checks', True)
                break

        response = self.get_response(request)
        return response

    def process_view(self, request, callback, callback_args, callback_kwargs):
        """
        Process view to ensure CSRF is exempt for API paths.
        This is called before the view is executed.
        """
        for path in self.EXEMPT_PATHS:
            if request.path.startswith(path):
                logger.info(f"CSRFExemptAPIMiddleware process_view: Exempting CSRF for path {request.path}")
                return None  # Return None to proceed without CSRF check
        return None
