.PHONY: push pull up down restart build logs clean

# Same push/pull convention as nginx-gateway and postgres-database, deployed
# from GitLab (this repo's server-facing remote); GitHub stays the public
# mirror. Unlike those two, ctts_api builds from its own Dockerfile, so pull
# rebuilds the image - just restarting stale code wouldn't pick up changes.

push:
	git add .
	git commit -m "update" || true
	git push gitlab main
	git push origin main

pull:
	git pull gitlab main
	cd backend && docker compose down
	cd backend && docker compose up -d --build

up:
	cd backend && docker compose up -d

down:
	cd backend && docker compose down

restart:
	cd backend && docker compose restart

build:
	cd backend && docker compose build

logs:
	cd backend && docker compose logs -f

clean:
	cd backend && docker compose down -v
