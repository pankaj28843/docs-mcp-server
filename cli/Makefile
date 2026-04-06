.PHONY: build install uninstall test bench clean

BINARY := docsearch
DATA_DIR := ../mcp-data

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
	go build -o $(BINARY) ./cmd/docsearch/

install: build
	@mkdir -p $(INSTALL_DIR)
	cp $(BINARY) $(INSTALL_DIR)/$(BINARY)
	@echo "Installed $(INSTALL_DIR)/$(BINARY)"

uninstall:
	rm -f $(INSTALL_DIR)/$(BINARY)
	@echo "Removed $(INSTALL_DIR)/$(BINARY)"

test:
	go test ./... -v

bench:
	@echo "=== Benchmarks ==="
	hyperfine --warmup 3 --min-runs 20 \
		'./$(BINARY) list --data-dir $(DATA_DIR)' \
		'./$(BINARY) find django --data-dir $(DATA_DIR)' \
		'./$(BINARY) search django middleware --data-dir $(DATA_DIR)' \
		'./$(BINARY) search react "useEffect cleanup" --data-dir $(DATA_DIR)' \
		'./$(BINARY) fetch django "https://docs.djangoproject.com/en/5.2/ref/middleware/" --data-dir $(DATA_DIR)'

clean:
	rm -f $(BINARY)
