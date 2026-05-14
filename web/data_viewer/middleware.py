from django.conf import settings
from django.http import HttpResponse


class SimpleCORSMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin", "")
        allowed_origin = self._allowed_origin(origin)

        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        if allowed_origin:
            response["Access-Control-Allow-Origin"] = allowed_origin
            response["Vary"] = self._merge_vary(response.get("Vary"), "Origin")
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-Requested-With"

        return response

    def _allowed_origin(self, origin):
        if not origin:
            return ""
        if origin in getattr(settings, "CORS_ALLOWED_ORIGINS", []):
            return origin
        return ""

    def _merge_vary(self, current_value, extra_value):
        if not current_value:
            return extra_value
        values = {item.strip() for item in current_value.split(",") if item.strip()}
        values.add(extra_value)
        return ", ".join(sorted(values))
