from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('manage/', admin.site.urls),  # TA dashboard, at a less-guessable path than /admin/
    path('', include('board.urls')),
]
