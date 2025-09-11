# notifications/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.demo_page, name='notifications-demo'),
    path('stream/', views.stream, name='notifications-stream'),
    path('push/', views.push, name='notifications-push'),
]
