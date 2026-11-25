from django.contrib import admin
from django.urls import path, include
from api.views import CreateUserView, CurrentUser
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/user/register/', CreateUserView.as_view(), name='register'),
    path('api/user/me/', CurrentUser.as_view(), name='current-user'),
    path('api/token/', TokenObtainPairView.as_view(), name='get_token'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='refresh_token'),
    path('api/movers/', include('movers.urls')),
    path('api/', include('api.urls')),
]
