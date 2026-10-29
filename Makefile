.PHONY: check test check-glossary

check: check-glossary
	@echo "Checking scripts and Python test files..."
	@if [ -d bin ]; then for f in bin/*; do \
		[ -f "$$f" ] || continue; \
		case "$$f" in \
			*.js) node --check "$$f" ;; \
			*) bash -n "$$f" ;; \
		esac; \
	done; fi
	@if [ -d tests ]; then python3 -m py_compile tests/*.py; fi

check-glossary:
	@node bin/check-glossary.js

test: check
	@if [ -d tests ]; then python3 -m unittest discover -s tests; else echo "No tests directory found."; fi
