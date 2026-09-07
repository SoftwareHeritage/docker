.PHONY: check-staged
check-staged:
	docker compose config -q

.PHONY: update-docker-image
update-docker-image:
	docker build --pull --no-cache-filter install_python_packages -t swh/stack .

.PHONY: pull-images-from-dockerhub
pull-images-from-dockerhub:
	docker compose $$(find compose.* -type f | sed -e 's/^/-f /') pull --ignore-buildable
