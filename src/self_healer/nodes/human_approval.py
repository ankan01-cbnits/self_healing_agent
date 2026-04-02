import os
import sys
import datetime
import subprocess
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box
from ..state import AgentState

def human_approval(state: AgentState) -> dict:
    console = Console()

    suggestion  = state["suggestion"]
    selector    = state["selector"]
    intent    = state["intent"]
    confidence  = float(state["confidence"])
    reason      = state["reason"]
    timestamp   = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    test_short  = state["test_name"].split("::")[-1]

    error_lines = state["error"].splitlines() if state["error"] else ["—"]
    error_short = next(
        (l.strip() for l in error_lines if "TimeoutError" in l or "Error:" in l),
        error_lines[0]
    )

    file_path   = state["file_path"]
    line_number = state["line_number"]
    base_dir    = Path(__file__).parent.parent.parent.parent

    # ── Header ────────────────────────────────────────────────────────────────
    header = Table.grid(expand=True)
    header.add_column()
    header.add_column(justify="right")
    header.add_row(
        Text("SELF-HEALING AGENT  —  HUMAN APPROVAL", style="bold bright_blue"),
        Text(timestamp, style="dim cyan"),
    )
    console.print(Panel(header, style="bright_blue", box=box.SQUARE, padding=(0, 1)))

    # ── TOP: Broken selector block ────────────────────────────────────────────
    broken = Table.grid(padding=(0, 2))
    broken.add_column(style="dim", no_wrap=True, min_width=12)
    broken.add_column(overflow="fold")

    broken.add_row(
        "SELECTOR",
        Text(f" {selector} ", style="bold white on red"),
    )
    broken.add_row(
        "ERROR",
        Text(error_short or "—", style="yellow"),
    )
    broken.add_row(
        "TEST",
        Text(test_short, style="dim"),
    )
    if file_path:
        try:
            rel = os.path.relpath(file_path, base_dir)
            broken.add_row("FILE", Text(f"{rel}:{line_number}", style="dim"))
        except ValueError:
            broken.add_row("FILE", Text(f"{file_path}:{line_number}", style="dim"))

    console.print(
        Panel(broken, title="[dim]broken selector[/dim]", title_align="left",
              border_style="red", box=box.SQUARE)
    )

    # ── MIDDLE: Arrow separator ───────────────────────────────────────────────
    console.print(Text("          ▼  llm suggestion", style="dim"))

    # ── BOTTOM: LLM suggestion block ─────────────────────────────────────────
    bar_width  = int((confidence / 100) * 24)
    conf_bar   = "█" * bar_width + "░" * (24 - bar_width)
    conf_label = "HIGH" if confidence >= 70 else "MED "

    fix = Table.grid(padding=(0, 2))
    fix.add_column(style="dim", no_wrap=True, min_width=12)
    fix.add_column(overflow="fold")

    fix.add_row(
        "FIX WITH",
        Text(f" {suggestion} ", style="bold white on green"),
    )
    fix.add_row(
        "CONFIDENCE",
        Text.assemble(
            (conf_bar, "green"), "  ",
            (f"{confidence:.1f}%", "bold green"), "  ",
            (f"[{conf_label}]", "bold white on blue"),
        ),
    )
    fix.add_row(
        "REASON",
        Text(reason or "N/A", style="white"),
    )
    fix.add_row(
        "INTENT",
        Text(f" {intent} ", style="bold white on white"),
    )

    console.print(
        Panel(fix, title="[dim]fix[/dim]", title_align="left",
              border_style="green", box=box.SQUARE)
    )

    # ── Footer ────────────────────────────────────────────────────────────────
    footer = Table.grid(expand=True)
    footer.add_column()
    footer.add_column(justify="right")
    footer.add_row(
        Text("self-healing-agent  ·  langgraph + groq", style="dim"),
        Text.assemble(
            ("[A]", "bold green"),  ("ccept   ", "default"),
            ("[R]", "bold red"),    ("eject   ", "default"),
            ("[C]", "bold cyan"),   ("opy",      "default"),
        ),
    )
    console.print(Panel(footer, border_style="dim", box=box.SQUARE, padding=(0, 1)))

    # ── Input ─────────────────────────────────────────────────────────────────
    approved = False
    console.print("[dim]Action [(A)ccept / (R)eject / (C)opy]: [/dim]", end="")

    try:
        if sys.platform == "win32":
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getch()
            key = msvcrt.getch()
            try:
                char = key.decode("utf-8").lower()
            except Exception:
                char = ""
        else:
            try:
                import tty, termios
                fd           = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    char = sys.stdin.read(1).lower()
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                char = input("").strip().lower()

        console.print(char.upper())

        if char == "a":
            approved = True
            console.print("[bold green]✓ Fix accepted. Applying...[/bold green]")
        elif char == "r":
            console.print("[bold red]✗ Fix rejected.[/bold red]")
        elif char == "c":
            _copy_to_clip(suggestion, console)
            console.print("[dim]Continuing without applying fix (copied to clipboard)[/dim]")

    except Exception:
        console.print("\n[dim]Continuing...[/dim]")

    return {
        "approved":    approved,
        "file_path":   file_path,
        "line_number": line_number,
    }


def _copy_to_clip(text: str, console: Console):
    try:
        if sys.platform == "win32":
            subprocess.run("clip", input=text.encode(), check=True)
        elif sys.platform == "darwin":
            subprocess.run("pbcopy", input=text.encode(), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text.encode(), check=True)
        console.print(f"[bold green]✓ Copied to clipboard:[/bold green] {text}")
    except Exception:
        console.print("[bold red]✗ Could not copy to clipboard[/bold red]")