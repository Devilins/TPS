#!/bin/bash

# Остановка всех контейнеров
docker-compose down

# Очистка старых сертификатов
rm -rf ./docker/certbot/conf/*
rm -rf ./docker/certbot/www/*

# Создание необходимых директорий
mkdir -p ./docker/certbot/conf
mkdir -p ./docker/certbot/www

# Запуск только nginx
docker-compose up -d nginx

# Ожидание запуска nginx
echo "Waiting for nginx to start..."
sleep 10

# Запрос сертификата
docker-compose run --rm --entrypoint "\
  certbot certonly --webroot \
    --webroot-path=/var/www/certbot \
    --email krivov145@gmail.com \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d takephoto-erp.ru \
" certbot

# После получения сертификатов раскомментируем SSL конфигурацию в nginx.conf
# и перезапускаем nginx
docker-compose restart nginx