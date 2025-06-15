IMAGE_NAME=tw-reservoir
CONTAINER_NAME=tw-reservoir
PYTHON=py
TRMNL_PLUGIN_ID=null

OPTIONS:=

up:
	docker start ${CONTAINER_NAME}

stop:
	docker stop ${CONTAINER_NAME}

shell: run
	docker exec -it ${CONTAINER_NAME} /bin/bash

build: venv/Scripts/activate

server: build
	. venv/Scripts/activate; $(PYTHON) -m main $(TRMNL_PLUGIN_ID)

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
