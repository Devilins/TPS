from threading import local
import traceback
import logging

_thread_locals = local()


# Middleware для получения текущего пользователя из запроса.
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


logger = logging.getLogger(__name__)


# Middleware для логирования всех ошибок. Стандартный способ логирования джанго логирует не все.
class ErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_exception(self, request, exception):
        logger.error(
            f"Unhandled exception: {str(exception)}\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        return None
