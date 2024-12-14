FROM python:3.12-slim

COPY . /app
WORKDIR /app

ENV PYTHONPATH=${PYTHONPATH}:${PWD}
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update \
    && apt-get -y install libpq-dev gcc
RUN pip install poetry
RUN poetry config virtualenvs.create false
RUN poetry install --only main

RUN poetry run python manage.py collectstatic --noinput

STOPSIGNAL SIGINT

