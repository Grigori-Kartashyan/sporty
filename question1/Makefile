IMAGE=config-resolver

.PHONY: build test

build:
	docker build -t $(IMAGE) .

test: build
	docker run --rm $(IMAGE) pytest -q
