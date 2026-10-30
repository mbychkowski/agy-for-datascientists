.PHONY: check test check-glossary

check: check-glossary
	@echo "Checking scripts and Python test files..."
	@if [ -d bin ]; then for f in bin/*; do \
		[ -f "$$f" ] || continue; \
		case "$$f" in \
			*.js) node --check "$$f" ;; \
			*.py) python3 -m py_compile "$$f" ;; \
			*) bash -n "$$f" ;; \
		esac; \
	done; fi
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check . && ruff format --check .; \
	elif [ -x /opt/uv/uvx ]; then \
		/opt/uv/uvx ruff check . && /opt/uv/uvx ruff format --check .; \
	elif [ -d tests ]; then \
		python3 -m py_compile tests/*.py lib/*.py; \
	fi

check-glossary:
	@node bin/check-glossary.js

test: check
	@if [ -d tests ]; then python3 -m unittest discover -s tests; else echo "No tests directory found."; fi
