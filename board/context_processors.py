def site(request):
    """Things the base template needs on every page."""
    from django.conf import settings

    from .models import SiteNotice

    return {
        "GOATCOUNTER_CODE": settings.GOATCOUNTER_CODE,
        "site_notice": SiteNotice.current() if not request.path.startswith("/manage/") else None,
    }
