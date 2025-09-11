import json
import time
from collections import deque
from django.http import StreamingHttpResponse, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.encoding import force_str
from django.shortcuts import render

# Create your views here.

# Process-local queue for demo only
_event_queue = deque()

def demo_page(request):
    return render(request, "notifications/index.html")

def _sse_format(data: str, event_id: str | None = None) -> str:
    """
    Format a string as an SSE event.
    Uses the required "data: " lines and blank line at the end.
    Optionally include an id: line (for Last-Event-ID handling later).
    """
    s = ""
    if event_id is not None:
        s += f"id: {event_id}\n"
    # Each line of data must be prefixed with "data: "
    for line in force_str(data).splitlines():
        s += f"data: {line}\n"
    s += "\n"
    return s

def stream(request):
    """
    SSE streaming endpoint using StreamingHttpResponse.
    WARNING: This is demo/demo-only: under WSGI each open connection occupies a worker.
    """

    # OPTIONAL: basic auth check could go here (session or token).
    # if not request.user.is_authenticated:
    #     return HttpResponse(status=401)

    def event_stream():
        # We will poll the in-memory queue. If empty, send a comment heartbeat to keep connection alive.
        try:
            while True:
                if _event_queue:
                    item = _event_queue.popleft()
                    payload = json.dumps(item)
                    yield _sse_format(payload)
                else:
                    # comment line (":") is ignored by EventSource clients; used to keep connection alive
                    yield ": keep-alive\n\n"
                    # small sleep to avoid busy loop. Tweak for latency/CPU tradeoff.
                    time.sleep(1)
        except GeneratorExit:
            # client disconnected, generator closed
            return

    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


@csrf_exempt  # demo only; in prod protect this endpoint
def push(request):
    """
    Accepts POST JSON and enqueues it for SSE clients.
    Example:
      curl -X POST -H "Content-Type: application/json" -d '{"message":"Hello"}' http://127.0.0.1:8000/notifications/push/
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        body = request.body.decode("utf-8")
        if not body:
            return JsonResponse({"error": "empty body"}, status=400)
        data = json.loads(body)
    except Exception:
        return JsonResponse({"error": "invalid json"}, status=400)

    # Build event object — add server timestamp & optional metadata
    event = {
        "message": data.get("message", ""),
        "meta": data.get("meta", {}),
        "timestamp": time.time(),
    }
    _event_queue.append(event)

    return JsonResponse({"ok": True, "queued": len(_event_queue)})