from django.http import JsonResponse

class RequireAuthHeaderMiddleware:
    """
    If the request is to /notifications/push/ and Authorization header is missing,
    return a 403 with a JSON error message.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/notifications/push/' and not request.META.get("HTTP_AUTHORIZATION"):
            return JsonResponse(
                {"error": "Missing Authorization header"},
                status=401
            )
        return self.get_response(request)