PYTHON ?= python
PORT ?= 8000

.PHONY: serve restart stop status

# Replace this checkout's server and reload Python edits automatically.
serve restart:
	$(PYTHON) mathdb_server.py restart --reload --port $(PORT)

stop status:
	$(PYTHON) mathdb_server.py $@ --port $(PORT)
