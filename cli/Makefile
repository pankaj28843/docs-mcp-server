.PHONY: build install test bench clean

BINARY := td
BUILD_DIR := .
DATA_DIR := ../mcp-data

build:
	go build -o $(BINARY) ./cmd/td/

install: build
	cp $(BINARY) ~/.local/bin/$(BINARY)

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
