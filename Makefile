.PHONY: push pull up down restart build logs clean

# Same push/pull convention as nginx-gateway and postgres-database. This repo
# has two remotes: GitHub (public mirror) and GitLab (server deploys from
# here). `origin` means different things on different machines - on a dev
# box it's whichever was cloned from first (GitHub here); on the server it's
# GitLab, since that's what gets cloned there. `pull` always targets `origin`
# so it works correctly on the server regardless of what it's named locally.
# Unlike nginx-gateway/postgres-database (off-the-shelf images), ctts_api
# builds from its own Dockerfile, so pull rebuilds the image - just
# restarting stale code wouldn't pick up changes.

push:
	git add .
	git commit -m "update" || true
	git push origin main
	-git push gitlab main

pull:
	git pull origin main
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
