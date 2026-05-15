IMAGE_NAME=tw-reservoir
CONTAINER_NAME=tw-reservoir
PYTHON=py
TRMNL_PLUGIN_API_KEY=null

OPTIONS:=

up:
	docker start ${CONTAINER_NAME}

stop:
	docker stop ${CONTAINER_NAME}

dockerbuild:
	docker build -t ${CONTAINER_NAME} .

dockerclean:
	docker stop ${CONTAINER_NAME} || true
	docker rm ${CONTAINER_NAME} || true

dockerrun: dockerclean
	docker run -d \
			--name ${CONTAINER_NAME} \
			--restart always \
			-p 8089:8080 \
			-e TRMNL_PLUGIN_API_KEY=$(TRMNL_PLUGIN_API_KEY) \
			${CONTAINER_NAME}

shell: run
	docker exec -it ${CONTAINER_NAME} /bin/bash

build: venv/Scripts/activate

server: build
	. venv/Scripts/activate; $(PYTHON) -m main

deploy:
	gcloud app deploy --project='reservoir-358117' --promote --stop-previous-version ${OPTIONS}

update:
	source venv/Scripts/activate && $(PYTHON) app/data.py >> public/reservoir-history/$$(date "+%Y").tsv
	git diff

clean:
	rm -rf venv

################################################

venv/Scripts/activate: requirements.txt
	$(PYTHON) -m venv venv
	. venv/Scripts/activate; pip install -r requirements.txt
