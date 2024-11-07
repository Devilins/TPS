from threading import local

_thread_locals = local()


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.request = request
        response = self.get_response(request)
        if hasattr(_thread_locals, 'request'):
            del _thread_locals.request
        return response


def get_current_user():
    if hasattr(_thread_locals, 'request'):
        return getattr(_thread_locals.request, 'user', None)
    return None
