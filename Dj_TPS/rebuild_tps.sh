#!/bin/bash

sudo docker compose stop
sudo docker container rm tps_system
sudo docker image rm dj_tps-tps
sudo docker compose up -d
sudo docker compose ps
