from django import forms

from .models import AcademicYear, Course, Post, Program


class BoardFilterForm(forms.Form):
    """Validates the board's query string: ?year=3&program=ds&course=12&type=assignment."""

    year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(),
        to_field_name="number",
        required=False,
        label="Level",
        empty_label="Choose level",
    )
    program = forms.ModelChoiceField(
        queryset=Program.objects.filter(is_active=True),
        to_field_name="slug",
        required=False,
        empty_label="Choose program",
    )
    course = forms.ModelChoiceField(
        queryset=Course.objects.none(), required=False, empty_label="All courses"
    )
    type = forms.ChoiceField(
        choices=[("", "All posts"), *Post.Kind.choices], required=False, label="Show"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Decided per request: students can only pick courses taught this semester.
        self.fields["course"].queryset = Course.objects.current()
