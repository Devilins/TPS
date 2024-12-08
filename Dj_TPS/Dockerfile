FROM python:3.12-slim

COPY . /app

WORKDIR /app

ENV PYTHONPATH=${PYTHONPATH}:${PWD}

RUN pip install poetry
RUN poetry config virtualenvs.create false
RUN poetry install --no-dev

STOPSIGNAL SIGINT

ENTRYPOINT poetry run python manage.py runserver
