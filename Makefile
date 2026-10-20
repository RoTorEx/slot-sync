.DEFAULT_GOAL := check
PYTHON ?= $(shell command -v python3.13 || command -v python3.11 || command -v python3)
export PYTHONPATH := $(CURDIR)/src
export PYTHONDONTWRITEBYTECODE := 1
DIST_DIR ?= $(HOME)/construction_side/slot-sync/dist
.PHONY: install check test build run version release release-push package-release vibe-pull vibe-propose
install:
	uv sync --frozen
check:
	$(PYTHON) scripts/check.py
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m slot_sync demo --json
	git diff --check
	git diff --cached --check
test:
	$(PYTHON) -m unittest discover -s tests -v
build:
	uv build --out-dir "$(DIST_DIR)"
package-release: build
	$(PYTHON) scripts/package.py "$(DIST_DIR)"
run:
	$(PYTHON) -m slot_sync $(ARGS)
version:
	$(PYTHON) -m slot_sync --version
release:
	$(PYTHON) scripts/release.py
release-push:
	$(PYTHON) scripts/release.py --push
vibe-pull:
	@kernel_root="$$(sed -n '1p' .vibe/KERNEL_SOURCE)"; python3 "$$kernel_root/tools/vibe-pull" .

# VIBE:KERNEL_MAKE_START

.PHONY: vibe-propose

vibe-propose:
	@test -f .vibe/KERNEL_SOURCE || { echo "Missing .vibe/KERNEL_SOURCE. Run: make vibe-kernel-set" >&2; exit 1; }
	@kernel_root="$$(sed -n '1p' .vibe/KERNEL_SOURCE)"; \
	test -f "$$kernel_root/tools/vibe-propose" || { echo "Missing $$kernel_root/tools/vibe-propose. Update the kernel source first." >&2; exit 1; }; \
	python3 "$$kernel_root/tools/vibe-propose" .

# VIBE:KERNEL_MAKE_END
