from django.contrib import admin

from .models import AcademicYear, Course, Post, Program, SiteNotice


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ["number", "name"]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active"]
    prepopulated_fields = {"slug": ["name"]}
    search_fields = ["name", "slug"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "year", "semester"]
    list_filter = ["year", "semester", "programs"]
    search_fields = ["code", "name"]  # also powers the course autocomplete on posts
    filter_horizontal = ["programs"]


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    """TAs see, edit and delete only their own posts. Superusers manage everything."""

    list_display = ["title", "kind", "course", "year", "program", "deadline", "published_at", "created_by"]
    list_filter = ["kind", "year", "program", "created_by"]  # filter by the bot to review imports
    search_fields = ["title", "body"]
    autocomplete_fields = ["course"]
    readonly_fields = ["created_by", "created_at", "updated_at", "source_id"]

    def _owns(self, request, obj):
        return obj is None or request.user.is_superuser or obj.created_by_id == request.user.pk

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(created_by=request.user)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._owns(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._owns(request, obj)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SiteNotice)
class SiteNoticeAdmin(admin.ModelAdmin):
    """"What's new" banner. Superusers only (TAs have no permission on this model)."""

    list_display = ["text", "is_active", "created_at"]
    list_editable = ["is_active"]
