package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/api"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/cache"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/config"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/service"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintf(os.Stderr, "docsearchd: %s\n", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, args []string, out, errOut io.Writer) error {
	flags := flag.NewFlagSet("docsearchd", flag.ContinueOnError)
	flags.SetOutput(errOut)
	var configPath, dataDir, deploymentConfig, listen string
	flags.StringVar(&configPath, "config", "", "shared docs-search configuration file")
	flags.StringVar(&dataDir, "data-dir", "", "override mcp-data directory")
	flags.StringVar(&deploymentConfig, "deployment-config", "", "override deployment.json path")
	flags.StringVar(&listen, "listen", "", "override listen address")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected arguments: %v", flags.Args())
	}
	path, err := config.Path(configPath)
	if err != nil {
		return err
	}
	cfg, err := config.Load(path)
	if err != nil {
		return err
	}
	if dataDir != "" {
		cfg.DataDir = dataDir
	}
	if deploymentConfig != "" {
		cfg.DeploymentConfig = deploymentConfig
	}
	if listen != "" {
		cfg.Listen = listen
	}
	if cfg.DataDir == "" {
		return fmt.Errorf("data_dir is required in %s or via --data-dir", path)
	}
	if err := cfg.Validate(); err != nil {
		return err
	}
	reader, err := service.New(cfg.DataDir, cfg.DeploymentConfig, cfg.SearchMaxConcurrent)
	if err != nil {
		return err
	}
	handler := api.NewHandler(reader, cache.New(cfg.CacheMaxBytes, time.Duration(cfg.CacheTTLSeconds)*time.Second))
	listener, err := net.Listen("tcp", cfg.Listen)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", cfg.Listen, err)
	}
	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      2 * time.Minute,
		IdleTimeout:       time.Minute,
		MaxHeaderBytes:    16 << 10,
	}
	if err := notifySystemd(fmt.Sprintf("READY=1\nSTATUS=Serving documentation on %s", listener.Addr())); err != nil {
		_ = listener.Close()
		return err
	}
	fmt.Fprintf(out, "docsearchd listening on %s using %s\n", listener.Addr(), cfg.DataDir)

	serveErrors := make(chan error, 1)
	go func() { serveErrors <- server.Serve(listener) }()
	select {
	case err := <-serveErrors:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		_ = notifySystemd("STOPPING=1\nSTATUS=Shutting down")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			return fmt.Errorf("shutdown: %w", err)
		}
		if err := <-serveErrors; err != nil && !errors.Is(err, http.ErrServerClosed) {
			return err
		}
		return nil
	}
}

func notifySystemd(state string) error {
	socket := os.Getenv("NOTIFY_SOCKET")
	if socket == "" {
		return nil
	}
	if socket[0] == '@' {
		socket = "\x00" + socket[1:]
	}
	connection, err := net.DialUnix("unixgram", nil, &net.UnixAddr{Name: socket, Net: "unixgram"})
	if err != nil {
		return fmt.Errorf("connect systemd notification socket: %w", err)
	}
	defer connection.Close()
	if _, err := connection.Write([]byte(state)); err != nil {
		return fmt.Errorf("notify systemd: %w", err)
	}
	return nil
}
