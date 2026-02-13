"""feedder-mcp: MCP server for academic paper collection."""



def main() -> None:
    """Entry point for the MCP server."""
    from src.client.cli import main as cli_main

    cli_main()

