from django.urls import path

from . import views

app_name = "board"

urlpatterns = [
    path("", views.board_list, name="list"),
    path("post/<int:pk>/", views.post_detail, name="post_detail"),
]
