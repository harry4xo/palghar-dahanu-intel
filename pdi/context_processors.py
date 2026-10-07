from . import vocab
from .models import Event, InboxItem


def nav(request):
    data = {"MICRO_MARKETS": vocab.MICRO_MARKETS}
    if request.user.is_authenticated and request.user.is_staff:
        data["nav_pending"] = Event.objects.filter(review_status=vocab.ReviewStatus.PENDING).count()
        data["nav_inbox"] = InboxItem.objects.filter(status=InboxItem.Status.NEW).count()
    return data
