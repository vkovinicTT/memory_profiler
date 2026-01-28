# SPDX-FileCopyrightText: (c) 2025 Tenstorrent AI ULC
#
# SPDX-License-Identifier: Apache-2.0

"""
Interactive CLI tool for TT Memory Profiler.

Provides a user-friendly interface for processing memory logs
and generating HTML reports.
"""

import http.server
import os
import socket
import socketserver
import sys
import threading
from pathlib import Path
from typing import Optional, Tuple

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.spinner import Spinner
    from rich.live import Live
    import questionary
except ImportError:
    print("Error: Required packages not found. Please install with:")
    print("  pip install rich questionary")
    sys.exit(1)

# Handle both package import and direct execution
try:
    from .parser import parse_log_file, validate_outputs
    from .visualizer import MemoryVisualizer
except ImportError:
    from parser import parse_log_file, validate_outputs
    from visualizer import MemoryVisualizer

# ASCII Logo using only - and | characters
LOGO = r"""
 |----|  |----|  |\    /|  |-----  |\    /|
   ||      ||    | \  / |  |       | \  / |
   ||      ||    |  \/  |  |----   |  \/  |
   ||      ||    |      |  |       |      |
   ||      ||    |      |  |-----  |      |
"""

console = Console()


def display_intro() -> None:
    """Display the ASCII logo and welcome message."""
    console.print(
        Panel(
            f"[cyan]{LOGO}[/cyan]\n[bold]Welcome to ttmem![/bold] Memory profiling made easy.",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def display_instructions() -> None:
    """Display prerequisites for generating memory logs."""
    instructions = """
[bold yellow]Prerequisites for Memory Logging:[/bold yellow]

[bold]1. Enable memory logging in TT-XLA:[/bold]
   Add this to your TT-XLA code:
   [cyan]tt::runtime::setMemoryLogLevel(tt::runtime::MemoryLogLevel::Operation)[/cyan]

[bold]2. Build TT-XLA with debug flags:[/bold]
   [cyan]-DCMAKE_BUILD_TYPE=Debug -DTT_RUNTIME_DEBUG=ON[/cyan]

[bold]3. Set the environment variable:[/bold]
   [cyan]export TTMLIR_RUNTIME_LOGGER_LEVEL=DEBUG[/cyan]

[bold]4. Run your model script:[/bold]
   [cyan]tt-memory-profiler --log path/to/your_model.py[/cyan]

   This will generate a log file at:
   [cyan]./logs/<script_name>_YYYYMMDD_HHMMSS/<script_name>_profile.log[/cyan]
"""
    console.print(
        Panel(
            instructions,
            title="[bold]Getting Started[/bold]",
            border_style="yellow",
            padding=(1, 2),
        )
    )


def ask_has_log_file() -> bool:
    """Ask the user if they already have a log file."""
    return questionary.confirm(
        "Have you generated the log file with memory logs?",
        default=False,
    ).ask()


def wait_for_ready() -> None:
    """Wait for the user to press Enter when ready."""
    console.print()
    questionary.press_any_key_to_continue(
        "Press Enter when you have your log file ready..."
    ).ask()


def ask_log_file_path() -> Optional[str]:
    """Prompt the user for the log file path with autocomplete."""
    console.print()
    path = questionary.path(
        "Enter the path to your log file:",
        only_directories=False,
        validate=lambda p: validate_log_path(p) is None or validate_log_path(p),
    ).ask()
    return path


def validate_log_path(path: str) -> Optional[str]:
    """
    Validate the log file path.

    Returns None if valid, or an error message string if invalid.
    """
    if not path:
        return "Path cannot be empty"

    file_path = Path(path)

    if not file_path.exists():
        return f"File not found: {path}"

    if not file_path.is_file():
        return f"Not a file: {path}"

    if not os.access(file_path, os.R_OK):
        return f"File is not readable: {path}"

    # Check if file has content
    if file_path.stat().st_size == 0:
        return f"File is empty: {path}"

    return None


def process_log_file(log_path: str) -> Optional[Path]:
    """
    Process the log file and generate the HTML report.

    Returns the path to the generated report, or None on failure.
    """
    log_file = Path(log_path)
    run_dir = log_file.parent

    # Determine script name from log file name
    # Expected format: <script_name>_profile.log
    log_name = log_file.name
    if log_name.endswith("_profile.log"):
        script_name = log_name[:-12]  # Remove "_profile.log"
    else:
        script_name = log_file.stem

    # Define output paths
    mem_output = run_dir / f"{script_name}_memory.json"
    ops_output = run_dir / f"{script_name}_operations.json"
    registry_output = run_dir / f"{script_name}_inputs_registry.json"

    console.print()

    # Step 1: Parse log file
    with console.status("[bold cyan]Parsing log file...", spinner="dots") as status:
        try:
            parse_log_file(
                str(log_file),
                str(mem_output),
                str(ops_output),
                str(registry_output),
            )
        except Exception as e:
            console.print(f"[red]Error parsing log file: {e}[/red]")
            return None

    # Step 2: Validate outputs
    with console.status("[bold cyan]Validating outputs...", spinner="dots") as status:
        if not validate_outputs(str(mem_output), str(ops_output)):
            console.print("[red]Output validation failed[/red]")
            return None

    # Step 3: Generate visualization
    with console.status("[bold cyan]Generating HTML report...", spinner="dots") as status:
        try:
            visualizer = MemoryVisualizer(run_dir)
            report_path = visualizer.generate_report()
        except Exception as e:
            console.print(f"[red]Error generating report: {e}[/red]")
            return None

    return report_path


def find_available_port(start_port: int = 8000, max_attempts: int = 100) -> int:
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("0.0.0.0", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"Could not find available port in range {start_port}-{start_port + max_attempts}")


def start_http_server(directory: Path, port: int) -> Tuple[socketserver.TCPServer, threading.Thread]:
    """Start an HTTP server in the background serving the given directory.

    Binds to 0.0.0.0 so VS Code Remote SSH can auto-forward the port.
    """
    handler = http.server.SimpleHTTPRequestHandler

    class QuietHandler(handler):
        """HTTP handler that suppresses log messages."""
        def log_message(self, format, *args):
            pass  # Suppress logging

    os.chdir(directory)
    # Bind to 0.0.0.0 to allow connections from any interface
    # This enables VS Code's automatic port forwarding for remote development
    server = socketserver.TCPServer(("0.0.0.0", port), QuietHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, thread


def ask_serve_http() -> bool:
    """Ask the user if they want to serve the report via HTTP."""
    return questionary.confirm(
        "Serve report via HTTP? (useful for remote access)",
        default=True,
    ).ask()


def display_success(report_path: Path, serve_http: bool = False) -> Optional[socketserver.TCPServer]:
    """
    Display success message with clickable link to the report.

    If serve_http is True, starts an HTTP server and returns the server instance.
    """
    # Create file:// URL
    file_url = f"file://{report_path.absolute()}"

    success_message = f"""
[bold green]Report generated successfully![/bold green]

[bold]Report location:[/bold]
[link={file_url}]{report_path}[/link]
"""

    server = None
    if serve_http:
        try:
            port = find_available_port()
            server, _ = start_http_server(report_path.parent, port)
            # Use localhost since VS Code Remote SSH will auto-forward the port
            http_url = f"http://localhost:{port}/{report_path.name}"

            success_message += f"""
[bold]HTTP URL (VS Code will auto-forward port {port}):[/bold]
[link={http_url}]{http_url}[/link]

[dim]Server running on port {port}. Press Ctrl+C to stop.[/dim]
"""
        except Exception as e:
            success_message += f"""
[yellow]Could not start HTTP server: {e}[/yellow]
[dim]You can manually serve the file with:[/dim]
[cyan]cd {report_path.parent} && python -m http.server[/cyan]
"""
    else:
        success_message += """
[dim]Click the link above or open the file in your browser.[/dim]
"""

    console.print(
        Panel(
            success_message,
            title="[bold green]Success[/bold green]",
            border_style="green",
            padding=(1, 2),
        )
    )

    return server


def main() -> int:
    """Main entry point for the interactive CLI."""
    try:
        # Display intro
        display_intro()

        # Ask if user has a log file
        has_log = ask_has_log_file()

        if has_log is None:
            # User cancelled (Ctrl+C)
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 1

        if not has_log:
            # Show instructions and wait for user
            display_instructions()
            wait_for_ready()

        # Get log file path
        log_path = ask_log_file_path()

        if log_path is None:
            # User cancelled
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 1

        # Validate path (questionary already validated, but double-check)
        error = validate_log_path(log_path)
        if error:
            console.print(f"[red]{error}[/red]")
            return 1

        # Process the log file
        report_path = process_log_file(log_path)

        if report_path is None:
            return 1

        # Ask if user wants HTTP serving
        serve_http = ask_serve_http()
        if serve_http is None:
            serve_http = False

        # Display success and optionally start server
        server = display_success(report_path, serve_http=serve_http)

        # If server is running, wait for Ctrl+C
        if server:
            try:
                console.print("\n[dim]Press Ctrl+C to stop the server and exit.[/dim]")
                while True:
                    pass
            except KeyboardInterrupt:
                server.shutdown()
                console.print("\n[yellow]Server stopped.[/yellow]")

        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 1
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
