"""Sarma CLI entry point."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

# Ensure UTF-8 output on Windows terminals for Unicode banner/icons
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


@click.group(invoke_without_command=True)
@click.option("--message", "-c", default=None, help="Single message (non-interactive).")
@click.version_option(package_name="sarma-cli")
@click.pass_context
def main(ctx, message):
    """Sarma — AI-powered vulnerability audit agent (CLI)."""
    ctx.ensure_object(dict)

    if ctx.invoked_subcommand is not None:
        return

    from sarma_cli.app import run_interactive, run_oneshot
    from sarma_cli.config import load_config

    config = load_config()

    if message:
        asyncio.run(run_oneshot(config, message))
    else:
        asyncio.run(run_interactive(config))


@main.command()
@click.option("--local", is_flag=True, help="Ensure this workspace has local Sarma directories.")
def init(local):
    """Initialize Sarma config files."""
    from sarma_cli.config import init_config
    init_config(local=local)


@main.command()
@click.argument("name", required=False)
def workflow(name):
    """List available workflows or switch to one.

    \b
    Examples:
      sarma workflow          # list all workflows
      sarma workflow audit    # switch to audit pipeline
      sarma workflow ruflo    # switch to Ruflo mode
    """
    from rich.console import Console
    from sarma_cli.workflows import get_registry, init_workflows

    init_workflows()
    registry = get_registry()
    console = Console()

    if not name:
        console.print("[bold]Available Workflows:[/]")
        for wf in registry.list_workflows():
            marker = "[bold cyan]*[/]" if wf.name == registry.current_name() else "[dim]-[/]"
            console.print(f"  {marker} [cyan]{wf.name:<10}[/] {wf.description}")
    else:
        if registry.switch(name):
            console.print(f"[green]Switched to[/] [cyan]{name}[/] workflow")
        else:
            console.print(f"[red]Unknown workflow:[/] {name}")
            raise SystemExit(1)


@main.command()
def plugin():
    """Manage MCP and skill plugins."""
    from sarma_cli.commands.plugins import cmd_plugin
    from sarma_cli.config import load_config

    restart = asyncio.run(cmd_plugin(load_config()))
    if restart:
        from rich.console import Console

        Console().print("[dim]Restart applies automatically in interactive sessions.[/]")


@main.command()
@click.option("--model", "embedding_model", default=None, help="Set the RAG embedding model name.")
@click.option(
    "--backend",
    "embedding_backend",
    type=click.Choice(["huggingface", "api"]),
    default=None,
    help="Set the RAG embedding backend.",
)
@click.option("--api-base", default=None, help="Set the embedding API base URL.")
@click.option("--api-key", default=None, help="Set the embedding API key.")
@click.option("--local-path", default=None, help="Set the local HuggingFace model path.")
@click.option("--pull", is_flag=True, help="Pull the HuggingFace embedding model locally.")
@click.option(
    "--split",
    "split_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Chunk documents from this file or directory.",
)
@click.option(
    "--add",
    "add_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Register an existing Chroma persistent database directory.",
)
@click.option("--name", default="", help="Knowledge base name. Defaults to the path name.")
@click.option(
    "--chroma-path",
    "--save-path",
    "chroma_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Chroma database output path for --split.",
)
@click.option(
    "--global",
    "global_scope",
    is_flag=True,
    help="Register --split/--add knowledge base in global rag.toml.",
)
def rag(
    embedding_model: str | None,
    embedding_backend: str | None,
    api_base: str | None,
    api_key: str | None,
    local_path: str | None,
    pull: bool,
    split_path: Path | None,
    add_path: Path | None,
    name: str,
    chroma_path: Path | None,
    global_scope: bool,
):
    """Manage RAG config, split documents, or add an existing Chroma database."""
    from rich.console import Console

    from sarma_cli.config import (
        KnowledgeBaseConfig,
        load_config,
        load_global_rag_config,
        load_local_rag_config,
        save_rag_knowledge_bases,
        save_rag_model,
    )
    from sarma_cli.resources.rag import (
        chunk_knowledge_base,
        pull_embedding_model,
        upsert_knowledge_base,
        validate_chroma_database,
    )

    console = Console()
    config = load_config()
    model_changed = False
    kb_changed = False
    kb_scope = "global" if global_scope else "local"
    scoped_rag = load_global_rag_config() if global_scope else load_local_rag_config()

    if embedding_model is not None:
        config.rag.embedding_model = embedding_model.strip()
        model_changed = True
    if embedding_backend is not None:
        config.rag.embedding_backend = embedding_backend
        model_changed = True
    if api_base is not None:
        config.rag.embedding_api_base = api_base.strip()
        model_changed = True
    if api_key is not None:
        config.rag.embedding_api_key = api_key.strip()
        model_changed = True
    if local_path is not None:
        config.rag.embedding_local_path = local_path.strip()
        model_changed = True

    if pull:
        result = pull_embedding_model(config.rag)
        config.rag.embedding_local_path = str(result.path)
        model_changed = True
        console.print(
            f"[green]Pulled[/] embedding model [cyan]{result.model}[/]: "
            f"[cyan]{result.path}[/]"
        )

    if split_path is not None:
        kb_name = _rag_kb_name(name, split_path)
        existing = next(
            (kb for kb in scoped_rag.knowledge_bases if kb.name == kb_name),
            None,
        )
        kb = KnowledgeBaseConfig(
            name=kb_name,
            docs_path=str(split_path.resolve()),
            chroma_path=str(chroma_path.resolve()) if chroma_path else (
                existing.chroma_path if existing else ""
            ),
            enabled=True,
        )
        upsert_knowledge_base(scoped_rag.knowledge_bases, kb)
        result = chunk_knowledge_base(kb, config.rag)
        kb_changed = True
        console.print(
            "[green]Chunked[/] "
            f"[cyan]{result.files}[/] file(s) into "
            f"[cyan]{result.chunks}[/] chunk(s): [cyan]{result.output_path}[/]"
        )

    if add_path is not None:
        chroma_path = add_path.resolve()
        try:
            chroma_info = validate_chroma_database(chroma_path)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        kb_name = _rag_kb_name(name, add_path)
        existing = next(
            (kb for kb in scoped_rag.knowledge_bases if kb.name == kb_name),
            None,
        )
        kb = KnowledgeBaseConfig(
            name=kb_name,
            docs_path=existing.docs_path if existing else "",
            chroma_path=str(chroma_path),
            enabled=True,
        )
        upsert_knowledge_base(scoped_rag.knowledge_bases, kb)
        kb_changed = True
        console.print(
            f"[green]Registered[/] Chroma database for [cyan]{kb_name}[/]: "
            f"[cyan]{chroma_info.path}[/]"
        )

    saved_paths: list[Path] = []
    if model_changed:
        saved_paths.append(save_rag_model(config))
    if kb_changed:
        saved_paths.append(save_rag_knowledge_bases(
            scoped_rag.knowledge_bases,
            scope=kb_scope,
        ))
    if saved_paths:
        for path in saved_paths:
            console.print(f"[green]Saved[/] [cyan]{path}[/]")
        return

    console.print("[bold]RAG[/]")
    console.print(f"  embedding_backend: [cyan]{config.rag.embedding_backend}[/]")
    console.print(f"  embedding_model: [cyan]{config.rag.embedding_model or '(unset)'}[/]")
    console.print(
        f"  embedding_api_base: [cyan]{config.rag.embedding_api_base or '(unset)'}[/]"
    )
    console.print(
        f"  embedding_local_path: "
        f"[cyan]{config.rag.embedding_local_path or '(default)'}[/]"
    )
    console.print(
        f"  chunk_size: [cyan]{config.rag.chunk_size}[/]  "
        f"chunk_overlap: [cyan]{config.rag.chunk_overlap}[/]"
    )
    if not config.rag.knowledge_bases:
        console.print("  knowledge_bases: [dim](none)[/]")
        return
    console.print("  knowledge_bases:")
    for kb in config.rag.knowledge_bases:
        marker = "[green]enabled[/]" if kb.enabled else "[dim]disabled[/]"
        console.print(
            f"    - [cyan]{kb.name}[/] {marker} "
            f"docs={kb.docs_path or '(default)'} "
            f"chroma={kb.chroma_path or '(default)'}"
        )


def _rag_kb_name(explicit: str, path: Path) -> str:
    if explicit.strip():
        return explicit.strip()
    return path.stem if path.is_file() else path.name


if __name__ == "__main__":
    main()
