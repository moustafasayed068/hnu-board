from django.urls import path

from . import ingest, telegram, views

app_name = "board"

urlpatterns = [
    path("", views.board_list, name="list"),
    path("post/<int:pk>/", views.post_detail, name="post_detail"),
    path("post/<int:pk>/calendar.ics", views.post_calendar, name="post_calendar"),
    # WhatsApp import, used only by whatsapp-bot/ (see board/ingest.py)
    path("ingest/", ingest.ingest_post, name="ingest_post"),
    path("ingest/courses/", ingest.ingest_courses, name="ingest_courses"),
    # Telegram import: Telegram calls this when you forward a post to the bot (see board/telegram.py)
    path("telegram/<str:secret>/", telegram.telegram_webhook, name="telegram_webhook"),
]
