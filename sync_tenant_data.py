#!/usr/bin/env python3
"""
Sync tenant data across machines using 7z archives.

This script exports and imports documentation data for each tenant individually,
allowing offline mode synchronization between machines. One machine runs in online
mode and periodically exports data for other machines to import.

Usage:
    # Export all tenants to default location
    uv run python sync_tenant_data.py export

    # Export specific tenants
    uv run python sync_tenant_data.py export --tenants django drf fastapi

    # Export to custom directory
    uv run python sync_tenant_data.py export --output ~/my-backup/

    # Import all tenants from default location
    uv run python sync_tenant_data.py import

    # Import specific tenants
    uv run python sync_tenant_data.py import --tenants django drf

    # Import from custom directory
    uv run python sync_tenant_data.py import --input ~/my-backup/

    # Dry run (show what would be done)
    uv run python sync_tenant_data.py export --dry-run
    uv run python sync_tenant_data.py import --dry-run
"""

import argparse
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",  # Simple format for console output
)
logger = logging.getLogger(__name__)


def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.resolve()


def get_home_dir() -> Path:
    """Get user's home directory."""
    return Path.home()


def get_default_export_dir() -> Path:
    """Get default export directory (~/docs-mcp-server-export/)."""
    return get_home_dir() / "docs-mcp-server-export"


def get_mcp_data_dir() -> Path:
    """Get mcp-data directory relative to script location."""
    return get_script_dir() / "mcp-data"


def get_deployment_json_path() -> Path:
    """Get deployment.json path relative to script location."""
    return get_script_dir() / "deployment.json"


def load_deployment_config() -> dict[str, Any]:
    """Load deployment.json configuration."""
    config_path = get_deployment_json_path()
    if not config_path.exists():
        logger.error("deployment.json not found at %s", config_path)
        sys.exit(1)

    try:
        with config_path.open(encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in deployment.json: %s", e)
        sys.exit(1)


def get_tenant_codenames() -> list[str]:
    """Extract all tenant codenames from deployment.json."""
    config = load_deployment_config()
    tenants = config.get("tenants", [])
    return [tenant["codename"] for tenant in tenants if "codename" in tenant]


def check_7z_installed() -> bool:
    """Check if 7z is installed and available."""
    try:
        result = subprocess.run(
            ["7z", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def export_tenant(
    tenant: str,
    output_dir: Path,
    mcp_data_dir: Path,
    dry_run: bool = False,
) -> bool:
    """
    Export a single tenant's data to a .7z archive.

    Args:
        tenant: Tenant codename (e.g., 'django', 'drf')
        output_dir: Directory to save the .7z archive
        mcp_data_dir: Path to mcp-data directory
        dry_run: If True, only show what would be done

    Returns:
        True if successful, False otherwise
    """
    tenant_data_dir = mcp_data_dir / tenant
    if not tenant_data_dir.exists():
        logger.warning("  Tenant data directory not found: %s", tenant_data_dir)
        return False

    output_archive = output_dir / f"{tenant}.7z"

    if dry_run:
        logger.info("  [DRY RUN] Would create: %s", output_archive)
        logger.info("  [DRY RUN] From: %s", tenant_data_dir)
        return True

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build 7z command
    # -mx9: Ultra compression
    # -mmt=on: Use multi-threading
    # -ms=on: Solid archive for better compression
    # -y: Assume yes on all queries (overwrite without prompt)
    cmd = [
        "7z",
        "a",  # Add to archive
        "-mx9",  # Ultra compression
        "-mmt=on",  # Multi-threading
        "-ms=on",  # Solid archive
        "-y",  # Assume yes (overwrite)
        str(output_archive),
        str(tenant_data_dir),
    ]

    try:
        logger.info("  Creating archive: %s", output_archive.name)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            # Get archive size
            size_mb = output_archive.stat().st_size / (1024 * 1024)
            logger.info("  ✓ Success: %s (%.2f MB)", output_archive.name, size_mb)
            return True
        logger.error("  ✗ Failed: %s", result.stderr.strip())
        return False

    except Exception as e:
        logger.error("  ✗ Error: %s", e)
        return False


def export_deployment_json(output_dir: Path, dry_run: bool = False) -> bool:
    """
    Copy deployment.json to export directory.

    Args:
        output_dir: Directory to copy deployment.json to
        dry_run: If True, only show what would be done

    Returns:
        True if successful, False otherwise
    """
    source = get_deployment_json_path()
    destination = output_dir / "deployment.json"

    if not source.exists():
        logger.warning("  deployment.json not found at %s", source)
        return False

    if dry_run:
        logger.info("  [DRY RUN] Would copy: %s -> %s", source, destination)
        return True

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        logger.info("  ✓ Copied: deployment.json")
        return True
    except Exception as e:
        logger.error("  ✗ Error copying deployment.json: %s", e)
        return False


def get_local_only_files(tenant_data_dir: Path, archive_path: Path) -> set[str]:
    """
    Get files that exist locally but not in the archive.

    Args:
        tenant_data_dir: Local tenant data directory
        archive_path: Path to the .7z archive

    Returns:
        Set of relative file paths that exist only locally
    """
    if not tenant_data_dir.exists():
        return set()

    # Get list of files in archive
    cmd = ["7z", "l", "-slt", str(archive_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return set()

    # Parse archive file list (7z -slt format groups entries with "Path = <path>"
    # and "Folder = +" for directories). We only want file entries here.
    archive_files: set[str] = set()
    current_path: str | None = None
    current_is_dir = False

    for line in list(result.stdout.splitlines()) + [""]:
        line = line.rstrip("\n")

        # Blank line separates entries; finalize the previous one.
        if not line:
            if current_path and not current_is_dir:
                # Path is relative to archive root (includes tenant folder name)
                parts = Path(current_path).parts
                # Remove tenant folder prefix if present
                if len(parts) > 1 and parts[0] == tenant_data_dir.name:
                    archive_files.add(str(Path(*parts[1:])))
                # Skip paths without tenant folder prefix (unexpected layout)
            current_path = None
            current_is_dir = False
            continue

        if line.startswith("Path = "):
            current_path = line[7:].strip()
            current_is_dir = False
            continue

        if line.startswith("Folder = "):
            value = line[9:].strip()
            # 7z uses "+" for directories
            current_is_dir = value in {"+", "1"}

    # Get local files
    local_files: set[str] = set()
    for file_path in tenant_data_dir.rglob("*"):
        if file_path.is_file():
            local_files.add(str(file_path.relative_to(tenant_data_dir)))

    return local_files - archive_files


def import_tenant(
    tenant: str,
    input_dir: Path,
    mcp_data_dir: Path,
    dry_run: bool = False,
    preserve_local: bool = True,
) -> bool:
    """
    Import a single tenant's data from a .7z archive.

    Args:
        tenant: Tenant codename (e.g., 'django', 'drf')
        input_dir: Directory containing the .7z archive
        mcp_data_dir: Path to mcp-data directory
        dry_run: If True, only show what would be done
        preserve_local: If True, preserve local files not in archive (default: True)

    Returns:
        True if successful, False otherwise
    """
    archive_path = input_dir / f"{tenant}.7z"
    if not archive_path.exists():
        logger.warning("  Archive not found: %s", archive_path)
        return False

    tenant_data_dir = mcp_data_dir / tenant

    # Track local-only files before import
    local_only_files: set[str] = set()
    if preserve_local and tenant_data_dir.exists():
        local_only_files = get_local_only_files(tenant_data_dir, archive_path)
        if local_only_files:
            logger.info("  Preserving %d local-only file(s)", len(local_only_files))

    if dry_run:
        logger.info("  [DRY RUN] Would extract: %s", archive_path.name)
        logger.info("  [DRY RUN] To: %s", mcp_data_dir)
        if local_only_files:
            logger.info("  [DRY RUN] Would preserve %d local-only file(s):", len(local_only_files))
            for f in sorted(local_only_files)[:5]:
                logger.info("    - %s", f)
            if len(local_only_files) > 5:
                logger.info("    ... and %d more", len(local_only_files) - 5)
        return True

    # Backup local-only files if preserving
    local_backups: dict[str, bytes] = {}
    if preserve_local and local_only_files:
        for rel_path in local_only_files:
            file_path = tenant_data_dir / rel_path
            if file_path.exists():
                try:
                    local_backups[rel_path] = file_path.read_bytes()
                except OSError as exc:
                    logger.warning("  Failed to back up local-only file %s: %s", file_path, exc)

    # Ensure mcp-data directory exists
    mcp_data_dir.mkdir(parents=True, exist_ok=True)

    # Build 7z command
    # x: Extract with full paths
    # -o: Output directory
    # -y: Assume yes on all queries (overwrite without prompt)
    cmd = [
        "7z",
        "x",  # Extract with full paths
        f"-o{mcp_data_dir}",  # Output directory
        "-y",  # Assume yes (overwrite)
        str(archive_path),
    ]

    try:
        logger.info("  Extracting: %s", archive_path.name)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            logger.error("  ✗ Failed: %s", result.stderr.strip())
            return False

        # Restore local-only files
        if local_backups:
            restored_count = 0
            failed_count = 0
            for rel_path, content in local_backups.items():
                file_path = tenant_data_dir / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    file_path.write_bytes(content)
                    restored_count += 1
                except OSError as e:
                    failed_count += 1
                    logger.warning("  ! Could not restore local-only file %s: %s", rel_path, e)
            if restored_count:
                logger.info("  ✓ Restored %d local-only file(s)", restored_count)
            if failed_count:
                logger.warning("  ! Failed to restore %d local-only file(s)", failed_count)

        logger.info("  ✓ Success: Extracted to %s", tenant_data_dir)
        return True

    except Exception as e:
        logger.error("  ✗ Error: %s", e)
        return False


def get_local_only_tenants(local_config: dict, remote_config: dict) -> list[dict]:
    """
    Find tenants that exist locally but not in the remote config.

    Args:
        local_config: Local deployment.json content
        remote_config: Remote deployment.json content

    Returns:
        List of tenant configs that exist only locally
    """
    remote_codenames = {t["codename"] for t in remote_config.get("tenants", [])}
    return [
        tenant
        for tenant in local_config.get("tenants", [])
        if tenant.get("codename") not in remote_codenames
    ]


def import_deployment_json(input_dir: Path, dry_run: bool = False) -> bool:
    """
    Import deployment.json from import directory, preserving local-only tenants.

    This merges the remote deployment.json with local-only tenants (e.g., danske_*
    tenants that only exist on this machine).

    Args:
        input_dir: Directory containing deployment.json
        dry_run: If True, only show what would be done

    Returns:
        True if successful, False otherwise
    """
    source = input_dir / "deployment.json"
    destination = get_deployment_json_path()

    if not source.exists():
        logger.warning("  deployment.json not found in import directory")
        return False

    # Load remote config
    try:
        with source.open(encoding="utf-8") as f:
            remote_config = json.load(f)
    except json.JSONDecodeError as e:
        logger.error("  ✗ Invalid JSON in remote deployment.json: %s", e)
        return False

    # Find local-only tenants to preserve
    local_only_tenants: list[dict] = []
    if destination.exists():
        try:
            with destination.open(encoding="utf-8") as f:
                local_config = json.load(f)
            local_only_tenants = get_local_only_tenants(local_config, remote_config)
        except json.JSONDecodeError:
            logger.warning("  ⚠ Could not parse local deployment.json, skipping tenant preservation")

    if dry_run:
        if destination.exists():
            logger.info("  [DRY RUN] Would backup: %s -> %s.backup", destination, destination)
        if local_only_tenants:
            logger.info("  [DRY RUN] Would preserve %d local-only tenant(s):", len(local_only_tenants))
            for t in local_only_tenants:
                logger.info("    - %s", t.get("codename", "unknown"))
        logger.info("  [DRY RUN] Would merge and import deployment.json")
        return True

    try:
        # Backup existing deployment.json if it exists
        if destination.exists():
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            backup_path = destination.parent / f"deployment.json.backup.{timestamp}"
            shutil.copy2(destination, backup_path)
            logger.info("  ✓ Backed up existing: %s", backup_path.name)

        # Merge local-only tenants into remote config
        if "tenants" not in remote_config:
            logger.error("  ✗ Remote config missing 'tenants' key")
            return False
        if local_only_tenants:
            remote_config["tenants"].extend(local_only_tenants)
            logger.info("  ✓ Preserved %d local-only tenant(s):", len(local_only_tenants))
            for t in local_only_tenants:
                logger.info("    - %s", t.get("codename", "unknown"))

        # Write merged deployment.json
        with destination.open("w", encoding="utf-8") as f:
            json.dump(remote_config, f, indent=2)
        logger.info("  ✓ Imported: deployment.json (%d tenants)", len(remote_config.get("tenants", [])))
        return True

    except Exception as e:
        logger.error("  ✗ Error importing deployment.json: %s", e)
        return False


def export_mode(args: argparse.Namespace) -> int:
    """
    Execute export mode.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    output_dir = Path(args.output).expanduser().resolve()
    mcp_data_dir = get_mcp_data_dir()

    logger.info("Export Configuration:")
    logger.info("  Output directory: %s", output_dir)
    logger.info("  MCP data directory: %s", mcp_data_dir)
    logger.info("  Dry run: %s", args.dry_run)
    logger.info("")

    if not check_7z_installed():
        logger.error("7z is not installed or not in PATH")
        logger.error("Install with: sudo apt install p7zip-full (Ubuntu/Debian)")
        logger.error("            or: brew install p7zip (macOS)")
        return 1

    # Get tenants to export
    tenants = args.tenants or get_tenant_codenames()

    if not tenants:
        logger.error("No tenants found in deployment.json")
        return 1

    logger.info("Exporting %d tenant(s)...", len(tenants))
    logger.info("")

    success_count = 0
    failure_count = 0

    # Export each tenant
    for tenant in tenants:
        logger.info("[%d/%d] %s", success_count + failure_count + 1, len(tenants), tenant)
        if export_tenant(tenant, output_dir, mcp_data_dir, args.dry_run):
            success_count += 1
        else:
            failure_count += 1

    # Export deployment.json
    logger.info("")
    logger.info("Exporting deployment.json...")
    if export_deployment_json(output_dir, args.dry_run):
        logger.info("")
    else:
        failure_count += 1

    # Summary
    logger.info("=" * 60)
    logger.info("Export Summary:")
    logger.info("  Success: %d/%d tenants", success_count, len(tenants))
    if failure_count > 0:
        logger.info("  Failed: %d", failure_count)
    if not args.dry_run:
        logger.info("  Location: %s", output_dir)
    logger.info("=" * 60)

    return 0 if failure_count == 0 else 1


def import_mode(args: argparse.Namespace) -> int:
    """
    Execute import mode.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    input_dir = Path(args.input).expanduser().resolve()
    mcp_data_dir = get_mcp_data_dir()

    preserve_local = not getattr(args, "no_preserve_local", False)
    logger.info("Import Configuration:")
    logger.info("  Input directory: %s", input_dir)
    logger.info("  MCP data directory: %s", mcp_data_dir)
    logger.info("  Preserve local files: %s", preserve_local)
    logger.info("  Dry run: %s", args.dry_run)
    logger.info("")

    if not input_dir.exists():
        logger.error("Input directory not found: %s", input_dir)
        return 1

    if not check_7z_installed():
        logger.error("7z is not installed or not in PATH")
        logger.error("Install with: sudo apt install p7zip-full (Ubuntu/Debian)")
        logger.error("            or: brew install p7zip (macOS)")
        return 1

    # Get tenants to import
    if args.tenants:
        tenants = args.tenants
    else:
        # Find all .7z files in input directory
        archives = list(input_dir.glob("*.7z"))
        tenants = [archive.stem for archive in archives]

    if not tenants:
        logger.error("No archives found in %s", input_dir)
        return 1

    logger.info("Importing %d tenant(s)...", len(tenants))
    logger.info("")

    success_count = 0
    failure_count = 0

    # Import each tenant
    for tenant in tenants:
        logger.info("[%d/%d] %s", success_count + failure_count + 1, len(tenants), tenant)
        if import_tenant(tenant, input_dir, mcp_data_dir, args.dry_run, preserve_local):
            success_count += 1
        else:
            failure_count += 1

    # Import deployment.json
    logger.info("")
    logger.info("Importing deployment.json...")
    if import_deployment_json(input_dir, args.dry_run):
        logger.info("")
    else:
        logger.info("  (continuing without deployment.json)")
        logger.info("")

    # Summary
    logger.info("=" * 60)
    logger.info("Import Summary:")
    logger.info("  Success: %d/%d tenants", success_count, len(tenants))
    if failure_count > 0:
        logger.info("  Failed: %d", failure_count)
    if not args.dry_run:
        logger.info("  Location: %s", mcp_data_dir)
    logger.info("=" * 60)

    return 0 if failure_count == 0 else 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync tenant documentation data across machines using 7z",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="mode", help="Operation mode", required=True)

    # Export subcommand
    export_parser = subparsers.add_parser(
        "export",
        help="Export tenant data to .7z archives",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        default=str(get_default_export_dir()),
        help=f"Output directory (default: {get_default_export_dir()})",
    )
    export_parser.add_argument(
        "--tenants",
        "-t",
        nargs="+",
        help="Specific tenants to export (default: all tenants from deployment.json)",
    )
    export_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually doing it",
    )

    # Import subcommand
    import_parser = subparsers.add_parser(
        "import",
        help="Import tenant data from .7z archives",
    )
    import_parser.add_argument(
        "--input",
        "-i",
        default=str(get_default_export_dir()),
        help=f"Input directory (default: {get_default_export_dir()})",
    )
    import_parser.add_argument(
        "--tenants",
        "-t",
        nargs="+",
        help="Specific tenants to import (default: all .7z files in input directory)",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually doing it",
    )
    import_parser.add_argument(
        "--no-preserve-local",
        action="store_true",
        help="Overwrite local files completely (default: preserve local-only files)",
    )

    args = parser.parse_args()

    if args.mode == "export":
        return export_mode(args)
    if args.mode == "import":
        return import_mode(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
