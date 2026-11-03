.PHONY: check test check-glossary lint-sh lint-tf

# Candidate paths for lint-sh; only files with a bash shebang are checked.
# $(wildcard) drops patterns that match nothing (e.g. bin/lib/ before it exists).
SH_CANDIDATES := $(wildcard bin/* bin/lib/* .agents/plugins/*/bin/* .husky/pre-commit)

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

lint-sh:
	@files=""; for f in $(SH_CANDIDATES); do \
		[ -f "$$f" ] || continue; \
		head -n 1 "$$f" | grep -Eq '^#!.*[/ ]bash([[:space:]]|$$)' && files="$$files $$f"; \
	done; \
	[ -n "$$files" ] || { echo "lint-sh: no bash scripts found" >&2; exit 1; }; \
	echo "shellcheck --severity=warning:$$files"; \
	uvx --from shellcheck-py shellcheck --severity=warning $$files

lint-tf:
	terraform -chdir=infra init -backend=false -lockfile=readonly -input=false
	terraform -chdir=infra validate
	terraform -chdir=infra fmt -check -recursive
