PIXI ?= pixi

.PHONY: help html clean

help:
	@echo "make html   Build the AsciiDoc documentation site with Pixi"
	@echo "make clean  Remove generated documentation"

html:
	cd .. && $(PIXI) run --locked -e docs docs-site

clean:
	rm -rf build
