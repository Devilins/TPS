from datetime import timedelta

from django import template

register = template.Library()


@register.filter('startswith')
def startswith(text, starts):
    if isinstance(text, str):
        return text.startswith(starts)
    return False


@register.filter
def add_days(date, days):
    if date is None:
        return ''
    else:
        return date + timedelta(days=int(days))


@register.filter('first_letter')
def first_letter(text):
    if isinstance(text, str):
        return text[0] + '.'
    return False
