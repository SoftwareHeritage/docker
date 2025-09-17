.PHONY: check-staged
check-staged:
	docker compose config -q

.PHONY: update-docker-image
update-docker-image:
	docker build --pull --no-cache -t swh/stack .
