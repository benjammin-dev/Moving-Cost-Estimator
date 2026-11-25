from django.urls import path

from . import views

urlpatterns = [
    path("", views.MoverList.as_view(), name="mover-list"),
    path("summary/", views.MoverSummary.as_view(), name="mover-summary"),
    path("imports/", views.ImportRuns.as_view(), name="mover-imports"),
    path("<int:pk>/", views.MoverDetail.as_view(), name="mover-detail"),
]
