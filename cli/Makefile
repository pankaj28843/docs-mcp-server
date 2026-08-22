.PHONY: build install uninstall test bench clean daemon-install daemon-start daemon-stop daemon-restart daemon-status

BINARY := docsearch
DAEMON := docsearchd
DATA_DIR := ../mcp-data
PKG := github.com/pankaj28843/docs-mcp-server/cli/cmd/docsearch

BUILD_TIME := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
COMMIT := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
VERSION := $(BUILD_TIME)

LDFLAGS := -X main.version=$(VERSION) -X main.buildTime=$(BUILD_TIME) -X main.commit=$(COMMIT)

# Install to first writable, in-PATH directory.
# Precedence: ~/.local/bin (user, no sudo) > /usr/local/bin (system, may need sudo)
INSTALL_DIR := $(shell \
	if [ -d "$$HOME/.local/bin" ] && echo "$$PATH" | grep -q "$$HOME/.local/bin"; then \
		echo "$$HOME/.local/bin"; \
	elif [ -w /usr/local/bin ]; then \
		echo "/usr/local/bin"; \
	else \
		echo "$$HOME/.local/bin"; \
	fi)

build:
	go build -ldflags '$(LDFLAGS)' -o $(BINARY) ./cmd/docsearch/
	go build -o $(DAEMON) ./cmd/docsearchd/

install: build
	@mkdir -p $(INSTALL_DIR)
	install -m 0755 $(BINARY) $(INSTALL_DIR)/.$(BINARY).new
	mv $(INSTALL_DIR)/.$(BINARY).new $(INSTALL_DIR)/$(BINARY)
	install -m 0755 $(DAEMON) $(INSTALL_DIR)/.$(DAEMON).new
	mv $(INSTALL_DIR)/.$(DAEMON).new $(INSTALL_DIR)/$(DAEMON)
	@echo "Installed $(INSTALL_DIR)/$(BINARY) and $(INSTALL_DIR)/$(DAEMON)"

daemon-install: install
	@mkdir -p $$HOME/.config/systemd/user
	install -m 0644 deploy/systemd/docsearchd.service $$HOME/.config/systemd/user/docsearchd.service
	systemctl --user daemon-reload
	systemctl --user enable docsearchd.service
	systemctl --user restart docsearchd.service

daemon-start:
	systemctl --user start docsearchd.service

daemon-stop:
	systemctl --user stop docsearchd.service

daemon-restart:
	systemctl --user restart docsearchd.service

daemon-status:
	systemctl --user --no-pager status docsearchd.service

uninstall:
	-systemctl --user disable --now docsearchd.service
	rm -f $(INSTALL_DIR)/$(BINARY) $(INSTALL_DIR)/$(DAEMON)
	@echo "Removed $(INSTALL_DIR)/$(BINARY) and $(INSTALL_DIR)/$(DAEMON)"

test:
	go test ./... -v

bench:
	@echo "=== Benchmarks ==="
	hyperfine --warmup 3 --min-runs 20 \
		'./$(BINARY) list --data-dir $(DATA_DIR)' \
		'./$(BINARY) find django --data-dir $(DATA_DIR)' \
		'./$(BINARY) search django middleware --data-dir $(DATA_DIR)' \
		'./$(BINARY) search react "useEffect cleanup" --data-dir $(DATA_DIR)' \
		'./$(BINARY) search django,fastapi,celery middleware --data-dir $(DATA_DIR)' \
		'./$(BINARY) search-all middleware --data-dir $(DATA_DIR)' \
		'./$(BINARY) fetch django "https://docs.djangoproject.com/en/5.2/ref/middleware/" --data-dir $(DATA_DIR)'

clean:
	rm -f $(BINARY) $(DAEMON)
