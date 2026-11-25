.PHONY: show control
PYTHON := .venv/bin/python

show:
	@test -n "$(WORKSPACE)" || { echo "usage: make show WORKSPACE=home.sloon"; exit 2; }
	$(PYTHON) -m sloon --workspace "$(WORKSPACE)" visualize

control:
	@test -n "$(WORKSPACE)" || { echo "usage: make control WORKSPACE=home.sloon"; exit 2; }
	$(PYTHON) -m sloon --workspace "$(WORKSPACE)" control
