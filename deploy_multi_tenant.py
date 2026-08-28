#!/usr/bin/env python3
"""Docs MCP server deployment script.

Usage:
    uv run python deploy_multi_tenant.py                              # Deploy with default deployment.json in offline mode
    uv run python deploy_multi_tenant.py --mode online                # Deploy in online mode (embedded worker)
    uv run python deploy_multi_tenant.py myconfig.json --mode offline # Deploy with custom config in offline mode

Online deployments run the crawler/indexer in the application container and
borrow one browser from a dedicated sidecar on a private Docker network.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

from rich.console import Console
from rich.table import Table


console = Console()


# Constants
DEFAULT_PROJECT = "docs-mcp-server"
BROWSER_CONTAINER = "docs-mcp-browser"
BROWSER_HOSTNAME = "docs-mcp-browser"
BROWSER_IMAGE = "chromedp/headless-shell@sha256:2d349b544a1ea6b5b5fd7c0fe99215ff662339c57407ee2e8c0a11af93516b04"
DOCKER_NETWORK = "docs-mcp-network"
_BROWSER_HEALTH_COMMAND = (
    "timeout 2 bash -c 'exec 3<>/dev/tcp/127.0.0.1/9222 && "
    'printf "GET /json/version HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n" >&3 && '
    "grep -q webSocketDebuggerUrl <&3'"
)


def get_docker_platform() -> str:
    """Detect host architecture and return appropriate Docker platform.

    Returns:
        Docker platform string (linux/amd64 or linux/arm64)
    """
    host_arch = platform.machine()
    if host_arch in ("arm64", "aarch64"):
        return "linux/arm64"
    return "linux/amd64"


def create_environment_config(
    source_config: Path,
    temp_config: Path,
    mode: str,
) -> tuple[Path, int, dict]:
    """Create deployment config.

    Args:
        source_config: Path to source deployment.json
        temp_config: Path for temporary config file
        mode: Operation mode

    Returns:
        Tuple of (config_path, port)
    """
    with source_config.open() as f:
        config = json.load(f)

    if mode == "online":
        config["infrastructure"]["browser_cdp_endpoint"] = f"http://{BROWSER_HOSTNAME}:9222"

    console.print("🔧 Using deployment configuration")

    # Write temporary config
    with temp_config.open("w") as f:
        json.dump(config, f, indent=2)

    port = config["infrastructure"]["mcp_port"]
    return temp_config, port, config


def resolve_signoz_provision_settings(config: dict) -> str | None:
    """Resolve SigNoz base URL for provisioning dashboards/alerts."""
    collector = config.get("infrastructure", {}).get("observability_collector", {})
    if not collector.get("enabled"):
        return None

    provision_flag = os.environ.get("SIGNOZ_PROVISION", "").lower()
    if provision_flag not in ("1", "true", "yes"):
        return None

    return os.environ.get("SIGNOZ_BASE_URL", "http://localhost:8080")


def provision_signoz_assets(base_url: str) -> None:
    """Provision SigNoz dashboards and alert rules via automation scripts."""
    script_path = Path("scripts/signoz-provision.py")
    if not script_path.exists():
        console.print("[yellow]⚠️  SigNoz provisioning script not found, skipping.[/yellow]")
        return

    args = [sys.executable, str(script_path), "--base-url", base_url]
    if os.environ.get("SIGNOZ_ENSURE_API_KEY", "").lower() in ("1", "true", "yes"):
        args.append("--ensure-api-key")
    if api_key_name := os.environ.get("SIGNOZ_API_KEY_NAME"):
        args.extend(["--api-key-name", api_key_name])
    if api_key_role := os.environ.get("SIGNOZ_API_KEY_ROLE"):
        args.extend(["--api-key-role", api_key_role])
    if api_key_expiry := os.environ.get("SIGNOZ_API_KEY_EXPIRY_DAYS"):
        args.extend(["--api-key-expiry-days", api_key_expiry])
    if dashboards_dir := os.environ.get("SIGNOZ_DASHBOARDS_DIR"):
        args.extend(["--dashboards-dir", dashboards_dir])
    if alerts_dir := os.environ.get("SIGNOZ_ALERTS_DIR"):
        args.extend(["--alerts-dir", alerts_dir])
    if os.environ.get("SIGNOZ_SKIP_DASHBOARDS", "").lower() in ("1", "true", "yes"):
        args.append("--skip-dashboards")
    if os.environ.get("SIGNOZ_SKIP_ALERTS", "").lower() in ("1", "true", "yes"):
        args.append("--skip-alerts")
    if os.environ.get("SIGNOZ_DRY_RUN", "").lower() in ("1", "true", "yes"):
        args.append("--dry-run")

    try:
        subprocess.run(args, check=True)
    except subprocess.CalledProcessError as exc:
        console.print(f"[yellow]⚠️  SigNoz provisioning failed: {exc}[/yellow]")


def deploy_docsearch_daemon(policy: str) -> bool:
    """Install or refresh the host daemon when explicitly configured.

    Auto mode is intentionally conservative: it acts only when the shared
    config or an existing user service is present. Require mode makes daemon
    installation failure fatal to the deployment.
    """
    if policy == "skip":
        return False

    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    shared_config = config_home / "docs-search" / "config.json"
    user_unit = config_home / "systemd" / "user" / "docsearchd.service"
    if policy == "auto" and not shared_config.exists() and not user_unit.exists():
        console.print("i  docsearchd is not configured; leaving the host service unchanged")
        return False
    if not shared_config.exists():
        message = f"docsearchd shared config is missing: {shared_config}"
        if policy == "require":
            raise RuntimeError(message)
        console.print(f"[yellow]⚠️  {message}; skipping daemon refresh[/yellow]")
        return False

    command = ["make", "-C", str(Path(__file__).parent / "cli"), "daemon-install"]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        if policy == "require":
            raise RuntimeError("docsearchd installation failed")
        console.print("[yellow]⚠️  docsearchd refresh failed; inspect the user service logs[/yellow]")
        return False
    console.print("✅ Host docsearchd service installed and restarted")
    return True


def get_filesystem_tenants(config_path: Path) -> tuple[list[str], list[str], Path]:
    """Extract filesystem tenant directories and create volume mount arguments.

    Strategy:
    - Mount entire mcp-data/ directory for all tenants (online and filesystem)
    - Only mount individual directories if they're OUTSIDE mcp-data/
    - This allows auto-creation of directories for new tenants during crawl

    Args:
        config_path: Path to deployment config

    Returns:
        Tuple of (volume_mount_args, tenant_codenames, mcp_data_dir)
    """
    with config_path.open() as f:
        config = json.load(f)

    # Determine mcp-data directory (default: ./mcp-data)
    script_dir = Path(__file__).parent
    mcp_data_dir = (script_dir / "mcp-data").resolve()

    # Create mcp-data if it doesn't exist
    mcp_data_dir.mkdir(parents=True, exist_ok=True)

    volume_args = []
    fs_tenants = []
    external_mounts = []

    # First, mount the entire mcp-data directory (read-write for auto-creation)
    volume_args.extend(["-v", f"{mcp_data_dir}:/tmp/mcp_data:rw"])
    console.print(f"📁 Mounting mcp-data: {mcp_data_dir} → /tmp/mcp_data")

    # Then, check for filesystem tenants with paths OUTSIDE mcp-data
    for tenant in config.get("tenants", []):
        if tenant.get("source_type") == "filesystem":
            docs_root = tenant.get("docs_root_dir")
            if docs_root:
                # Expand home directory
                docs_root = Path(docs_root).expanduser().resolve()

                # Check if this path is OUTSIDE mcp-data
                try:
                    # This will raise ValueError if docs_root is not relative to mcp_data_dir
                    docs_root.relative_to(mcp_data_dir)
                    # Path is INSIDE mcp-data, no need for individual mount
                    is_inside_mcp_data = True
                except ValueError:
                    # Path is OUTSIDE mcp-data, needs individual mount
                    is_inside_mcp_data = False

                if not is_inside_mcp_data:
                    # Mount external directory individually
                    if docs_root.exists():
                        codename = tenant.get("codename", "unknown")
                        container_path = f"/mnt/docs/{codename}"

                        volume_args.extend(["-v", f"{docs_root}:{container_path}:rw"])
                        external_mounts.append((codename, docs_root, container_path))
                        fs_tenants.append(codename)
                    else:
                        console.print(
                            f"[yellow]⚠️  Warning: External filesystem path does not exist: {docs_root}[/yellow]"
                        )
                else:
                    # Path inside mcp-data, will be accessible via main mount
                    codename = tenant.get("codename", "unknown")
                    fs_tenants.append(codename)
                    console.print(f"   {codename}: Using mcp-data mount (no individual mount needed)")

    # Show external mounts if any
    if external_mounts:
        console.print("\n📁 External filesystem tenants (outside mcp-data):")
        for codename, host_path, container_path in external_mounts:
            console.print(f"   • {codename}: {host_path} → {container_path}")

    return volume_args, fs_tenants, mcp_data_dir


def update_filesystem_paths(config_path: Path, mcp_data_dir: Path) -> None:
    """Update deployment config to use container paths for all tenants with docs_root_dir.

    Strategy:
    - All tenants with docs_root_dir inside mcp-data: Map to /tmp/mcp_data mount
    - Tenants outside mcp-data (filesystem type): Update to /mnt/docs/{codename} container path

    This applies to ALL tenant types (online, filesystem, git) that have docs_root_dir,
    not just filesystem tenants.

    Args:
        config_path: Path to deployment config
        mcp_data_dir: Path to mcp-data directory
    """
    console.print("🔧 Updating tenant paths to container mount points...")

    with config_path.open() as f:
        config = json.load(f)

    updated_any = False
    for tenant in config.get("tenants", []):
        docs_root_str = tenant.get("docs_root_dir", "")
        if not docs_root_str:
            continue

        codename = tenant.get("codename")
        source_type = tenant.get("source_type", "online")
        docs_root = Path(docs_root_str).expanduser().resolve()

        # Check if path is inside mcp-data
        try:
            relative_path = docs_root.relative_to(mcp_data_dir)
            # Inside mcp-data - map to /tmp/mcp_data structure
            container_path = f"/tmp/mcp_data/{relative_path}"
            tenant["docs_root_dir"] = container_path
            console.print(f"  {codename} ({source_type}): {container_path} (via mcp-data mount)")
            updated_any = True
        except ValueError:
            # Outside mcp-data - only filesystem tenants get individual mounts
            if source_type == "filesystem":
                container_path = f"/mnt/docs/{codename}"
                tenant["docs_root_dir"] = container_path
                console.print(f"  {codename} ({source_type}): {container_path} (external mount)")
                updated_any = True
            else:
                console.print(f"  {codename} ({source_type}): path outside mcp-data, skipping")

    if updated_any:
        with config_path.open("w") as f:
            json.dump(config, f, indent=2)
    else:
        console.print("  No tenants with docs_root_dir to update")


def sync_python_environment() -> None:
    """Sync Python environment and update lock file."""
    console.print("📦 Syncing Python environment and updating lock file...")
    subprocess.run(["uv", "sync"], check=True)


def build_docker_image(dockerfile: str, docker_platform: str, tag: str) -> None:
    """Build Docker image with specified platform.

    Args:
        dockerfile: Path to Dockerfile
        docker_platform: Docker platform string
        tag: Docker image tag
    """
    user_id = os.getuid()
    group_id = os.getgid()
    host_arch = platform.machine()

    console.print(f"🐳 Building Docker image: {tag}...")
    console.print(f"🔧 Using platform: {docker_platform} (detected from host: {host_arch})")
    console.print(f"👤 Building with user UID:GID = {user_id}:{group_id}")

    extra_build_args = []
    if os.environ.get("http_proxy"):
        extra_build_args.extend(["--build-arg", f"http_proxy={os.environ.get('http_proxy')}"])
    if os.environ.get("https_proxy"):
        extra_build_args.extend(["--build-arg", f"https_proxy={os.environ.get('https_proxy')}"])
    if os.environ.get("no_proxy"):
        extra_build_args.extend(["--build-arg", f"no_proxy={os.environ.get('no_proxy')}"])

    subprocess.run(
        [
            "docker",
            "buildx",
            "build",
            "--load",
            "--platform",
            docker_platform,
            "-f",
            dockerfile,
            "--build-arg",
            f"USER_ID={user_id}",
            "--build-arg",
            f"GROUP_ID={group_id}",
            *extra_build_args,
            "-t",
            tag,
            ".",
        ],
        check=True,
    )


def stop_existing_container(container_name: str) -> None:
    """Stop and remove existing container if running.

    Args:
        container_name: Name of container to stop
    """
    # Check if container exists
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )

    if container_name in result.stdout.splitlines():
        console.print(f"🛑 Stopping existing container: {container_name}")
        subprocess.run(["docker", "stop", container_name], capture_output=True, check=False)
        subprocess.run(["docker", "rm", container_name], capture_output=True, check=False)


def wait_for_port_release(port: int, timeout_seconds: float = 10) -> None:
    """Wait for Docker's host-port proxy to release a stopped container's port."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                pass
        except OSError:
            return
        time.sleep(0.1)
    raise TimeoutError(f"Host port {port} was not released within {timeout_seconds}s")


def ensure_docker_network(network_name: str) -> None:
    """Create the private application/browser network when absent."""
    result = subprocess.run(
        ["docker", "network", "inspect", network_name],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        subprocess.run(["docker", "network", "create", "--driver", "bridge", network_name], check=True)


def run_browser_container(platform: str, network_name: str) -> None:
    """Start the single externally owned browser without publishing CDP ports."""
    console.print("🌐 Starting shared headless browser on the private Docker network...")
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--init",
            "--restart",
            "unless-stopped",
            "--name",
            BROWSER_CONTAINER,
            "--hostname",
            BROWSER_HOSTNAME,
            "--network",
            network_name,
            "--network-alias",
            BROWSER_HOSTNAME,
            "--platform",
            platform,
            "--shm-size",
            "2g",
            "--health-cmd",
            _BROWSER_HEALTH_COMMAND,
            "--health-interval",
            "1s",
            "--health-timeout",
            "3s",
            "--health-retries",
            "20",
            "--health-start-period",
            "2s",
            BROWSER_IMAGE,
        ],
        check=True,
    )


def wait_for_browser_container(timeout_seconds: float = 30) -> None:
    """Wait until Chrome's version endpoint is reachable inside the sidecar."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", BROWSER_CONTAINER],
            capture_output=True,
            text=True,
            check=False,
        )
        status = result.stdout.strip()
        if result.returncode == 0 and status == "healthy":
            return
        if status == "unhealthy":
            raise RuntimeError(f"Browser sidecar failed its health check: {BROWSER_CONTAINER}")
        time.sleep(0.25)
    raise TimeoutError(f"Browser sidecar did not become healthy within {timeout_seconds}s")


def wait_for_application_container(container_name: str, timeout_seconds: float = 90) -> None:
    """Wait until the application has completed its fail-fast startup checks."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        state = result.stdout.strip()
        if result.returncode == 0 and state == "running healthy":
            return
        if result.returncode != 0 or not state.startswith("running ") or state.endswith(" unhealthy"):
            raise RuntimeError(f"Application container failed its health check: {container_name} ({state})")
        time.sleep(0.25)
    raise TimeoutError(f"Application container did not become healthy within {timeout_seconds}s")


def run_container(
    container_name: str,
    port: int,
    config_path: Path,
    volume_mounts: list[str],
    mode: str,
    platform: str,
    network_name: str,
) -> None:
    """Run Docker container with specified configuration.

    Args:
        container_name: Name for the container
        port: Port to expose
        config_path: Path to deployment config
        volume_mounts: Volume mount arguments
        mode: Operation mode (online/offline)
        platform: Docker platform string
        network_name: Private application/browser network
    """
    console.print(f"🚀 Starting container on port {port} in {mode} mode...")

    # Get config directory
    config_dir = Path(__file__).parent / "config"

    # Base command
    cmd = [
        "docker",
        "run",
        "-d",
        "--init",
        "--restart",
        "unless-stopped",
        "--name",
        container_name,
        "--platform",
        platform,
        "--network",
        network_name,
        "-p",
        f"{port}:{port}",
        "-v",
        f"{config_path.resolve()}:/app/deployment.json:ro",
        "-v",
        f"{config_dir.resolve()}:/app/config:ro",
    ]

    # Add volume mounts
    cmd.extend(volume_mounts)

    # Add environment variables
    # Note: LOG_LEVEL is intentionally NOT set here so the container uses
    # the log_profile from deployment.json (handled by AppBuilder)
    cmd.extend(
        [
            "-e",
            "DEPLOYMENT_CONFIG=/app/deployment.json",
            "-e",
            f"OPERATION_MODE={mode}",
            "-e",
            f"MCP_PORT={port}",
        ]
    )

    fallback_token = os.environ.get("DOCS_FALLBACK_EXTRACTOR_TOKEN")
    if fallback_token:
        cmd.extend(["-e", f"DOCS_FALLBACK_EXTRACTOR_TOKEN={fallback_token}"])

    article_proxies = os.environ.get("ARTICLE_PROXIES") or os.environ.get("RSS_WRAPPER_PROXY_POOL")
    if article_proxies:
        cmd.extend(["-e", f"ARTICLE_PROXIES={article_proxies}"])

    # Add host gateway
    cmd.extend(["--add-host=host.docker.internal:host-gateway"])

    # Add image
    cmd.append("pankaj28843/docs-mcp-server:multi-tenant")

    # Run container
    subprocess.run(cmd, check=True)


def show_deployment_summary(
    dockerfile: str,
    docker_platform: str,
    port: int,
    config_path: Path,
    container_name: str,
    mcp_data_dir: Path,
    mode: str,
) -> None:
    """Show deployment summary with tenant information.

    Args:
        dockerfile: Dockerfile used
        docker_platform: Docker platform
        port: Port number
        config_path: Path to original config
        container_name: Container name
        mcp_data_dir: Path to mcp-data directory
        mode: Operation mode (online/offline)
    """
    console.print("\n✅ Deployment complete!\n", style="bold green")

    # Basic info
    host_arch = platform.machine()
    table = Table(title="Deployment Information")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Mode", mode)
    table.add_row("Dockerfile", dockerfile)
    table.add_row("Platform", f"{docker_platform} (host: {host_arch})")
    table.add_row("Server URL", f"http://127.0.0.1:{port}")
    table.add_row("Health Check", f"http://127.0.0.1:{port}/health")
    table.add_row("MCP Endpoint", f"http://127.0.0.1:{port}/mcp")
    table.add_row("Data Directory", str(mcp_data_dir))

    console.print(table)

    # Container info
    console.print("\n🐳 Containers:\n", style="bold")
    console.print(f"   • [cyan]Docs MCP[/cyan]: {container_name} (serves HTTP + embedded worker)")
    if mode == "online":
        console.print(f"   • [cyan]Browser[/cyan]: {BROWSER_CONTAINER} (one shared headless Chrome root)")

    # Volume mounts
    console.print("\n📁 Volume mounts:\n", style="bold")
    console.print(f"   • [cyan]mcp-data[/cyan]: {mcp_data_dir} → /tmp/mcp_data (auto-creates tenant directories)")
    # Filesystem tenants (external mounts)
    with config_path.open() as f:
        config = json.load(f)

    external_tenants = []
    for tenant in config.get("tenants", []):
        if tenant.get("source_type") == "filesystem":
            codename = tenant.get("codename")
            docs_root = Path(tenant.get("docs_root_dir", "")).expanduser().resolve()

            # Check if outside mcp-data
            try:
                docs_root.relative_to(mcp_data_dir)
                is_external = False
            except ValueError:
                is_external = True

            if is_external and docs_root.exists():
                external_tenants.append((codename, docs_root))

    if external_tenants:
        console.print("\n📁 External filesystem tenants (outside mcp-data):\n", style="bold")
        for codename, docs_root in external_tenants:
            docs_name = next(
                (t.get("docs_name", codename) for t in config.get("tenants", []) if t.get("codename") == codename),
                codename,
            )
            console.print(f"   • [cyan]{codename}[/cyan]: {docs_name}")
            console.print(f"     Host: [yellow]{docs_root}[/yellow]")
            console.print(f"     Container: [green]/mnt/docs/{codename}[/green]")
            console.print(f"     URL: [blue]http://127.0.0.1:{port}/{codename}/mcp[/blue]")

    console.print(f"\nView logs: [cyan]docker logs -f {container_name}[/cyan]")
    stop_names = f"{container_name} {BROWSER_CONTAINER}" if mode == "online" else container_name
    console.print(f"Stop deployment: [cyan]docker stop {stop_names}[/cyan]")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Deploy multi-tenant docs MCP server")
    parser.add_argument(
        "config",
        nargs="?",
        default="deployment.json",
        help="Path to deployment config (default: deployment.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["online", "offline"],
        default="offline",
        help="Operation mode (default: offline)",
    )
    parser.add_argument(
        "--docsearch-daemon",
        choices=["auto", "skip", "require"],
        default="auto",
        help="Refresh the host docsearchd service when configured (default: auto)",
    )

    args = parser.parse_args()

    # Print header
    console.rule("[bold blue]Multi-Tenant Docs MCP Server Deployment[/bold blue]")

    # Validate config file
    config_file = Path(args.config)
    if not config_file.exists():
        console.print(f"[red]❌ Error: Config file not found: {config_file}[/red]")
        console.print("Please create a deployment.json file. See deployment.example.json for reference.")
        return 1

    # Use standard Dockerfile
    dockerfile = "Dockerfile"
    if not Path(dockerfile).exists():
        console.print(f"[red]❌ Error: Dockerfile not found: {dockerfile}[/red]")
        return 1

    console.print(f"Config: {args.config}")
    console.print(f"Mode: {args.mode}\n")

    # Get script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    # Get Docker platform
    docker_platform = get_docker_platform()

    # Sync Python environment
    sync_python_environment()

    # Create deployment config
    temp_config = Path("deployment.docker.json")
    temp_config, port, config = create_environment_config(config_file, temp_config, args.mode)

    # Get filesystem tenants and volume mounts
    volume_mounts, fs_tenants, mcp_data_dir = get_filesystem_tenants(temp_config)

    if fs_tenants:
        console.print(f"✅ Found filesystem tenants: {', '.join(fs_tenants)}")
        console.print(f"   Volume mounts: {' '.join(volume_mounts)}")
    else:
        console.print("i  No filesystem tenants with valid paths found")

    # Update filesystem paths in config
    update_filesystem_paths(temp_config, mcp_data_dir)

    # Build Docker images
    build_docker_image(dockerfile, docker_platform, "pankaj28843/docs-mcp-server:multi-tenant")

    # Stop existing containers before replacing either owner.
    container_name = "docs-mcp-server-multi"
    stop_existing_container(container_name)
    wait_for_port_release(port)
    stop_existing_container(BROWSER_CONTAINER)

    ensure_docker_network(DOCKER_NETWORK)
    if args.mode == "online":
        run_browser_container(docker_platform, DOCKER_NETWORK)
        try:
            wait_for_browser_container()
        except Exception:
            stop_existing_container(BROWSER_CONTAINER)
            raise

    # Run MCP server container
    try:
        run_container(
            container_name=container_name,
            port=port,
            config_path=temp_config,
            volume_mounts=volume_mounts,
            mode=args.mode,
            platform=docker_platform,
            network_name=DOCKER_NETWORK,
        )
        wait_for_application_container(container_name)
    except Exception:
        stop_existing_container(container_name)
        if args.mode == "online":
            stop_existing_container(BROWSER_CONTAINER)
        raise

    signoz_base_url = resolve_signoz_provision_settings(config)
    if signoz_base_url:
        provision_signoz_assets(signoz_base_url)

    try:
        deploy_docsearch_daemon(args.docsearch_daemon)
    except RuntimeError as exc:
        console.print(f"[red]❌ Error: {exc}[/red]")
        return 1

    # Show summary
    show_deployment_summary(
        dockerfile=dockerfile,
        docker_platform=docker_platform,
        port=port,
        config_path=config_file,
        container_name=container_name,
        mcp_data_dir=mcp_data_dir,
        mode=args.mode,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
