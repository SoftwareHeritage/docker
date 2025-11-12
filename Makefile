.PHONY: check-staged
check-staged:
	docker compose config -q

.PHONY: update-docker-image
update-docker-image:
	docker build --pull --no-cache-filter install_python_packages -t swh/stack .
