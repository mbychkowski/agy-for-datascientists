.PHONY: check test

check:
	@echo "Checking shell scripts and Python test files..."
	@if [ -d bin ]; then for f in bin/*; do [ -f "$$f" ] && bash -n "$$f"; done; fi
	@if [ -d tests ]; then python3 -m py_compile tests/*.py; fi

test: check
	@if [ -d tests ]; then python3 -m unittest discover -s tests; else echo "No tests directory found."; fi
