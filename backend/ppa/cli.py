"""PPA-Profiler command line interface."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import Session

from .config import settings
from .db import get_engine, init_db

app = typer.Typer(help="PPA-Profiler: RISC-V PPA analysis workbench", no_args_is_help=True)
console = Console()


@app.command("init")
def init():
    """Create the SQLite database."""
    init_db()
    console.print(f"[green]initialized[/green] {settings.db_path}")


@app.command("gen-sample")
def gen_sample(out_dir: Path = typer.Argument(None)):
    """Generate synthetic RTLA/PrimePower/SPECint sample runs."""
    from .sample_data import generate
    target = out_dir or settings.sample_dir
    files = generate(target)
    console.print(f"[green]generated[/green] {len(files)} files under {target}")


@app.command("ingest")
def ingest(dir_path: Path = typer.Argument(..., help="run directory with manifest.json"),
           project: str = typer.Option("riscv-demo")):
    """Parse reports under a run directory and load them into the DB."""
    from .ingest import ingest_directory
    init_db()
    with Session(get_engine()) as session:
        result = ingest_directory(session, dir_path, project)
    t = Table(title="Ingest result")
    t.add_column("item")
    t.add_column("value")
    t.add_row("project_id", str(result["project_id"]))
    t.add_row("runs ingested", str(len(result["runs"])))
    t.add_row("findings raised", str(result["findings"]))
    console.print(t)


@app.command("demo")
def demo(dir_path: Path = typer.Argument(None)):
    """Generate sample data and ingest it in one step."""
    from .ingest import ingest_directory
    from .sample_data import generate
    target = dir_path or settings.sample_dir
    generate(target)
    init_db()
    with Session(get_engine()) as session:
        result = ingest_directory(session, target, "riscv-demo")
    console.print(f"[green]demo ready[/green]: {len(result['runs'])} runs, "
                  f"{result['findings']} findings in {settings.db_path}")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Run the API + web UI."""
    import uvicorn
    uvicorn.run("ppa.main:app", host=host, port=port, reload=reload)


@app.command("check-format")
def check_format(file: Path = typer.Argument(...)):
    """Try parsing one report file and print what the parser extracted."""
    from .parsers import primepower, rtla, specint
    text = file.read_text(errors="replace")
    parsers = [
        ("rtla_area", rtla.parse_rtla_area), ("rtla_timing", rtla.parse_rtla_timing),
        ("rtla_qor", rtla.parse_rtla_qor), ("primepower", primepower.parse_primepower),
        ("specint", specint.parse_specint),
    ]
    for name, fn in parsers:
        try:
            rep = fn(text)
            rows = len(getattr(rep, "rows", []) or getattr(rep, "groups", [])
                       or getattr(rep, "metrics", {}))
            warn = len(getattr(rep, "warnings", []) or [])
            console.print(f"[green]{name}[/green]: parsed {rows} rows, {warn} warnings")
            for w in (getattr(rep, "warnings", None) or [])[:5]:
                console.print(f"  warning: {w}")
            return
        except Exception:  # noqa: BLE001
            continue
    console.print("[red]no parser matched this file[/red]")


if __name__ == "__main__":
    app()
