"""
Authentication views for user management.
"""
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.conf import settings
from django_ratelimit.decorators import ratelimit
from .serializers import UserSerializer, RegisterSerializer, PasswordChangeSerializer


def get_client_ip(request):
    """Extract client IP for rate limiting."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom token serializer that includes user data in response."""

    def validate(self, attrs):
        data = super().validate(attrs)
        # Add user data to response
        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
            'first_name': self.user.first_name,
            'last_name': self.user.last_name,
        }
        return data


@method_decorator(
    ratelimit(key='ip', rate=getattr(settings, 'RATELIMIT_AUTH', '5/m'), method='POST', block=True),
    name='post'
)
class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom token view that returns user data along with tokens."""
    serializer_class = CustomTokenObtainPairSerializer


class CurrentUserView(APIView):
    """Get current authenticated user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


@method_decorator(
    ratelimit(key='ip', rate=getattr(settings, 'RATELIMIT_AUTH', '5/m'), method='POST', block=True),
    name='post'
)
class RegisterView(generics.CreateAPIView):
    """Register a new user."""
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer


class LogoutView(APIView):
    """Logout user by blacklisting refresh token."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            return Response(
                {'message': 'Successfully logged out'},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


@method_decorator(
    ratelimit(key='user', rate=getattr(settings, 'RATELIMIT_AUTH', '5/m'), method='POST', block=True),
    name='post'
)
class PasswordChangeView(APIView):
    """Change password for authenticated user."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(
                {'message': 'Password changed successfully'},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
