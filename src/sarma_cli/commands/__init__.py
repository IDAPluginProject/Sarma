"""Slash command catalog for the full-screen TUI."""

COMMANDS: dict[str, str] = {
    "/help": "Show available commands",
    "/status": "Show model, MCP servers, and skills status",
    "/graph": "Show current workflow execution graph",
    "/workflow": "List workflows or switch workflow (/workflow <name>)",
    "/plugin": "Manage MCP and skill plugins",
    "/restart": "Restart current workflow runtime",
    "/models": "Show configured models",
    "/history": "List past conversations",
    "/resume": "Resume a previous conversation (/resume <id>)",
    "/clear": "Clear current session history",
    "/compact": "Compact conversation context",
    "/config": "Add or edit named models (saves to ./.sarma/models.toml)",
    "/exit": "Exit Sarma CLI",
}
