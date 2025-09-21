# notifications/views.py
import json
import time
from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.utils.encoding import force_str
from django.conf import settings
from django.contrib.auth import get_user_model
from oauth2_provider.decorators import protected_resource

User = get_user_model()

from .models import Notification
from .utils import create_and_publish, _redis_client as redis_client

def _sse_format(data: str, event_id: str | None = None) -> str:
    """Format a string as an SSE event block (id: ... \n data: ... \n\n)."""
    s = ""
    if event_id is not None:
        s += f"id: {event_id}\n"
    for line in force_str(data).splitlines():
        s += f"data: {line}\n"
    s += "\n"
    return s

def demo_page(request):
    """Render the demo HTML page (index.html)"""
    return render(request, "notifications/index.html")


def stream(request):
    """
    SSE stream view (sync).
    Behavior:
      1) Determine user_id (optional) and last_event_id from request.
      2) Replay persisted notifications from Postgres with id > last_event_id.
      3) Subscribe to Redis channel and forward new messages as SSE events (including id:).
      4) Do a small post-subscribe DB check to reduce the race window.
    Note: This is a synchronous implementation suitable for local/dev testing.
    """
    # Optional: in a later step require authentication here (request.user)
    user_id = request.GET.get("user_id")
    last_event_id = request.META.get("HTTP_LAST_EVENT_ID") or request.GET.get("last_id")
    try:
        last_event_id = int(last_event_id) if last_event_id else 0
    except (TypeError, ValueError):
        last_event_id = 0

    channel = f"notifications:user:{user_id}" if user_id else "notifications:global"

    def event_stream():
        last_sent = last_event_id or 0

        # 1) Replay: send persisted notifications with id > last_sent
        if last_sent:
            if user_id:
                missed_qs = Notification.objects.filter(user_id=user_id, id__gt=last_sent).order_by("id")
            else:
                missed_qs = Notification.objects.filter(user__isnull=True, id__gt=last_sent).order_by("id")
            for n in missed_qs:
                payload = json.dumps({
                    "id": n.id,
                    "user_id": n.user_id,
                    "payload": n.payload,
                    "created_at": n.created_at.isoformat(),
                }, separators=(",", ":"))
                yield _sse_format(payload, event_id=str(n.id))
                last_sent = max(last_sent, n.id)

        # 2) Subscribe to Redis for live messages
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel)

        # 3) Race mitigation: check DB again for any rows written while subscribing
        if last_sent:
            if user_id:
                pending = Notification.objects.filter(user_id=user_id, id__gt=last_sent).order_by("id")
            else:
                pending = Notification.objects.filter(user__isnull=True, id__gt=last_sent).order_by("id")
            for n in pending:
                payload = json.dumps({
                    "id": n.id,
                    "user_id": n.user_id,
                    "payload": n.payload,
                    "created_at": n.created_at.isoformat(),
                }, separators=(",", ":"))
                yield _sse_format(payload, event_id=str(n.id))
                last_sent = max(last_sent, n.id)

        # 4) Listen to Redis and forward messages
        try:
            for item in pubsub.listen():
                if not item:
                    continue
                if item.get("type") != "message":
                    continue
                raw = item.get("data")
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except Exception:
                        continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    # if not JSON, wrap raw payload
                    msg = {"payload": raw}

                msg_id = msg.get("id")
                # avoid sending duplicates
                if msg_id and last_sent and int(msg_id) <= int(last_sent):
                    continue

                payload_text = json.dumps(msg, separators=(",", ":"))
                yield _sse_format(payload_text, event_id=str(msg.get("id")) if msg.get("id") else None)
                if msg.get("id"):
                    last_sent = max(last_sent, int(msg.get("id")))
        except GeneratorExit:
            # client disconnected; clean up pubsub
            try:
                pubsub.close()
            except Exception:
                pass
            return
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


@csrf_exempt
@protected_resource()
def push(request):
    """
    Persist + publish endpoint.
    Accepts JSON body like:
    { "message": "...", "meta": {...}, "user_id": <optional> }
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        body = request.body.decode("utf-8")
        data = json.loads(body) if body else {}
    except Exception:
        return JsonResponse({"error": "invalid json"}, status=400)

    payload = {"message": data.get("message"), "meta": data.get("meta", {})}
    user_id = data.get("user_id")

    # check if its a valid user
    if user_id is not None:
        try:
            user_id = int(user_id)
            User.objects.get(pk=user_id)
        except (ValueError, User.DoesNotExist):
            return JsonResponse(
                {"error": "user not found"},
                status=400
            )

    # Persist to DB and publish to Redis (create_and_publish returns Notification instance)
    n = create_and_publish(user_id, payload)

    return JsonResponse({"ok": True, "id": n.id})
