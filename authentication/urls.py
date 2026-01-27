"""
Authentication URL configuration.
"""
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenRefreshView,
    TokenVerifyView,
)
from . import views

urlpatterns = [
    # JWT Token endpoints (custom view includes user data)
    path('token/', views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # User endpoints
    path('user/', views.CurrentUserView.as_view(), name='current_user'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('password/change/', views.PasswordChangeView.as_view(), name='password_change'),
]
