"""CLI entry point — click-based commands."""
import click

from amas_code import config as config_mod, skills, ui
from amas_code.agent import Agent


@click.group(invoke_without_command=True)
@click.argument("prompt", required=False, default=None)
@click.option("--model", "-m", default=None, help="Override model (e.g. gemini/gemini-2.5-flash)")
@click.pass_context
def main(ctx, prompt: str | None, model: str | None) -> None:
    """Amas Code — AI coding agent for any model, any hardware."""
    if ctx.invoked_subcommand is not None:
        return

    cfg = config_mod.load()
    if model:
        cfg["model"] = model

    agent = Agent(cfg)

    if prompt:
        agent.chat_turn(prompt)
    else:
        agent.run()


@main.command()
@click.argument("provider", required=False, default=None)
@click.argument("key", required=False, default=None)
@click.option("--model", "-m", default=None, help="Set default model")
def config(provider: str | None, key: str | None, model: str | None) -> None:
    """Configure API keys and model. Run without args for interactive setup."""
    if model:
        config_mod.set_model(model)
        ui.show_config_saved("model", model)
        return

    if provider and key:
        config_mod.set_api_key(provider, key)
        ui.show_config_saved(f"api_keys.{provider}", f"{key[:8]}...{'*' * 8}")
        return

    # Interactive config wizard
    _config_wizard()


def _config_wizard() -> None:
    """Interactive first-run setup wizard."""
    ui.console.print("\n[bold bright_cyan]🔧 Amas Code — Configuration Wizard[/]\n")

    cfg = config_mod.load()

    # Model selection
    ui.info("Select your default model:")
    for i, m in enumerate(config_mod.KNOWN_MODELS, 1):
        marker = " [green]◀ current[/]" if m == cfg.get("model") else ""
        ui.console.print(f"  [cyan]{i:2}.[/] {m}{marker}")

    choice = ui.prompt_input("Enter number or model name (press Enter to keep current)")
    if choice:
        if choice.isdigit() and 1 <= int(choice) <= len(config_mod.KNOWN_MODELS):
            cfg["model"] = config_mod.KNOWN_MODELS[int(choice) - 1]
        else:
            cfg["model"] = choice
        ui.success(f"Model set to: [cyan]{cfg['model']}[/]")

    # API key setup
    model = cfg["model"]
    provider = model.split("/")[0] if "/" in model else config_mod._guess_provider(model)
    if provider:
        existing = config_mod.resolve_api_key(cfg)
        if existing:
            ui.info(f"API key for [cyan]{provider}[/] already configured.")
            change = ui.prompt_input("Change it? (y/n)")
            if change.lower() not in ("y", "yes"):
                provider = ""  # Skip

        if provider:
            env_var = config_mod.PROVIDER_ENV_VARS.get(provider, "")
            hint = f" (or set env var [cyan]{env_var}[/])" if env_var else ""
            key = ui.prompt_input(f"Enter API key for {provider}{hint}", password=True)
            if key:
                if "api_keys" not in cfg:
                    cfg["api_keys"] = {}
                cfg["api_keys"][provider] = key
                ui.success(f"API key for [cyan]{provider}[/] saved.")

    config_mod.save(cfg)
    ui.success("Configuration saved to [cyan].amas/config.yaml[/]")
    ui.console.print()


@main.command()
def init() -> None:
    """Scan project structure and extract symbols."""
    cfg = config_mod.load()
    result = skills.init_project(".", cfg)
    ui.console.print(f"\n{result}")


if __name__ == "__main__":
    main()
