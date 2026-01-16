"""
Custom authentication for pcc API key authentication.
"""
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from collectors.models import Collector


class APIKeyAuthentication(BaseAuthentication):
    """
    API Key authentication for pcc clients.

    Expects header: Authorization: ApiKey <key>
    Or query param: ?api_key=<key>
    """

    def authenticate(self, request):
        # Try header first
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('ApiKey '):
            api_key = auth_header[7:]  # Remove 'ApiKey ' prefix
        elif auth_header.startswith('Bearer '):
            # Also accept Bearer for compatibility
            api_key = auth_header[7:]
        else:
            # Try query param
            api_key = request.query_params.get('api_key')

        if not api_key:
            return None  # No API key provided, let other auth methods try

        try:
            collector = Collector.objects.select_related('owner').get(api_key=api_key)
        except Collector.DoesNotExist:
            raise AuthenticationFailed('Invalid API key')

        # Attach collector to request for use in views
        request.collector = collector

        # Return (user, auth) tuple
        return (collector.owner, api_key)

    def authenticate_header(self, request):
        return 'ApiKey'
