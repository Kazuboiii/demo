from django.http import JsonResponse


def health(request):
    """Identity probe for local discovery; deliberately contains no user data."""
    return JsonResponse({"service": "homs", "version": 1})
