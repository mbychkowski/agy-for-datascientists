.PHONY: check check-docs test check-glossary lint-sh lint-tf

# Candidate paths for lint-sh. A file is checked when line 1 is a bash or sh shebang
# (sh for .husky/pre-commit, which husky runs with `sh -e`) or, for sourced libraries,
# `# shellcheck shell=bash`. Every file in bin/lib/ must carry one of these.
# $(wildcard) drops patterns that match nothing (e.g. a missing bin/lib/).
SHELLCHECK := uvx --from shellcheck-py==0.11.0.1 shellcheck
SH_CANDIDATES := $(wildcard bin/* bin/lib/* .agents/plugins/*/bin/* .husky/pre-commit)
SH_MARKER := ^(\#!.*[/ ](ba)?sh([[:space:]]|$$)|\# shellcheck shell=bash)

check: check-glossary
	@echo "Checking scripts and Python test files..."
	@if [ -d bin ]; then for f in bin/* bin/lib/*; do \
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

# Fast loop for docs-only changes (DEMO.md, docs/, GLOSSARY.md): glossary, ruff and
# the doc test modules, in seconds. The pre-commit hook still runs the full guardrail.
DOC_TESTS := tests/test_runbook_and_reuser_docs.py tests/test_primer_and_outline.py \
	tests/test_fallback_trigger_timing.py tests/test_check_glossary.py \
	tests/test_worktree_workflow.py tests/test_check_docs_target.py

check-docs: check-glossary
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check . && ruff format --check .; \
	else \
		/opt/uv/uvx ruff check . && /opt/uv/uvx ruff format --check .; \
	fi
	python3 -m unittest $(patsubst tests/%.py,tests.%,$(DOC_TESTS))

test: check
	@if [ -d tests ]; then python3 -m unittest discover -s tests; else echo "No tests directory found."; fi

lint-sh:
	@files=""; for f in $(SH_CANDIDATES); do \
		[ -f "$$f" ] || continue; \
		if head -n 1 "$$f" | grep -Eq '$(SH_MARKER)'; then files="$$files $$f"; \
		elif [ "$${f#bin/lib/}" != "$$f" ]; then \
			echo "lint-sh: $$f needs a bash shebang or '# shellcheck shell=bash' on line 1" >&2; exit 1; \
		fi; \
	done; \
	[ -n "$$files" ] || { echo "lint-sh: no bash scripts found" >&2; exit 1; }; \
	echo "shellcheck:$$files"; \
	$(SHELLCHECK) --severity=warning $$files && \
	$(SHELLCHECK) --severity=info --include=SC1090,SC1091 $$files

lint-tf:
	terraform -chdir=infra init -backend=false -lockfile=readonly -input=false
	terraform -chdir=infra validate
	terraform -chdir=infra fmt -check -recursive
