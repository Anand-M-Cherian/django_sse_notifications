# notifications/utils.py
import json
import redis
from django.conf import settings
from .models import Notification

# Redis client configured from settings (defaults if not set)
_redis_client = redis.Redis(
    host=getattr(settings, "REDIS_HOST", "127.0.0.1"),
    port=getattr(settings, "REDIS_PORT", 6379),
    db=getattr(settings, "REDIS_DB", 0),
    decode_responses=False,  # we encode/decode explicitly below
)

def _channel_for_user(user_id):
    """Return channel name for a user_id or global channel when user_id is falsy."""
    return f"notifications:user:{user_id}" if user_id else "notifications:global"

def create_and_publish(user_id, payload):
    """
    Persist Notification (Postgres) and publish JSON message to Redis channel.
    Returns the created Notification instance.
    """
    # Persist first to get DB id (for replay/resume)
    if user_id:
        n = Notification.objects.create(user_id=user_id, payload=payload)
    else:
        n = Notification.objects.create(payload=payload)

    # Build message including DB id so consumers can resume from id
    message = {
        "id": n.id,
        "user_id": n.user_id,
        "payload": n.payload,
        "created_at": n.created_at.isoformat(),
    }

    channel = _channel_for_user(user_id)
    # publish as bytes (consistent with earlier code that decodes)
    _redis_client.publish(channel, json.dumps(message, separators=(",", ":")).encode("utf-8"))
    return n
