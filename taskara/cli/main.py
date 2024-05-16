from typing import Optional
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkgversion

import typer
from namesgenerator import get_random_name
from tabulate import tabulate
import rich


art = """
 _______         _                       
(_______)       | |                      
    _ _____  ___| |  _ _____  ____ _____ 
   | (____ |/___) |_/ |____ |/ ___|____ |
   | / ___ |___ |  _ (/ ___ | |   / ___ |
   |_\_____(___/|_| \_)_____|_|   \_____|
                                         
"""

app = typer.Typer()

# Sub-command groups
create_group = typer.Typer(help="Create resources")
list_group = typer.Typer(help="List resources")
get_group = typer.Typer(help="Get resources")
view_group = typer.Typer(help="View resources")
delete_group = typer.Typer(help="Delete resources")
clean_group = typer.Typer(help="Clean resources")

app.add_typer(create_group, name="create")
app.add_typer(list_group, name="list")
app.add_typer(get_group, name="get")
app.add_typer(view_group, name="view")
app.add_typer(delete_group, name="delete")
app.add_typer(clean_group, name="clean")


# Callback for showing help
def show_help(ctx: typer.Context, command_group: str):
    if ctx.invoked_subcommand is None:
        if command_group == "root":
            typer.echo(art)
        typer.echo(ctx.get_help())
        raise typer.Exit()


try:
    __version__ = pkgversion("surfkit")
except PackageNotFoundError:
    # Fallback version or error handling
    __version__ = "unknown"


@app.command(help="Show the version of the CLI")
def version():
    """Show the CLI version."""
    typer.echo(__version__)


# Root command callback
@app.callback(invoke_without_command=True)
def default(ctx: typer.Context):
    show_help(ctx, "root")


# 'create' command group callback
@create_group.callback(invoke_without_command=True)
def create_default(ctx: typer.Context):
    show_help(ctx, "create")


# 'list' command group callback
@list_group.callback(invoke_without_command=True)
def list_default(ctx: typer.Context):
    show_help(ctx, "list")


# 'get' command group callback
@get_group.callback(invoke_without_command=True)
def get_default(ctx: typer.Context):
    show_help(ctx, "get")


# 'delete' command group callback
@delete_group.callback(invoke_without_command=True)
def delete_default(ctx: typer.Context):
    show_help(ctx, "delete")


# 'view' command group callback
@view_group.callback(invoke_without_command=True)
def view_default(ctx: typer.Context):
    show_help(ctx, "view")


# 'clean' command group callback
@clean_group.callback(invoke_without_command=True)
def clean_default(ctx: typer.Context):
    show_help(ctx, "clean")


# 'create' sub-commands
@create_group.command("task")
def create_task(
    description: str = typer.Option(
        ...,
        "--description",
        "-d",
        help="Description of the task. Defaults to a generated name.",
    ),
    remote: bool = typer.Option(True, "--remote", "-r", help="List tasks from remote"),
):
    from taskara import Task

    typer.echo(f"Creating task '{description}'")
    try:
        task = Task(description=description)
    except KeyboardInterrupt:
        print("Keyboard interrupt received, exiting...")
        return
