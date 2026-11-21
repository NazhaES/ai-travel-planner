"""Minimal local MCP server for aviationstack (airports + airlines reference data)."""
import os

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Aviationstack MCP Server")

API_KEY = os.getenv("AVIATION_STACK_API_KEY", "")
BASE = "http://api.aviationstack.com/v1"


def _get(endpoint: str, params: dict) -> list[dict]:
    if not API_KEY:
        return [{"error": "AVIATIONSTACK_API_KEY is missing"}]
    params = {**params, "access_key": API_KEY, "limit": params.get("limit", 10)}
    data = requests.get(f"{BASE}/{endpoint}", params=params, timeout=20).json()
    if isinstance(data, dict) and "error" in data:
        return [{"error": data["error"].get("message", "aviationstack error")}]
    return data.get("data", []) if isinstance(data, dict) else []


@mcp.tool()
def list_airports(search: str = "", limit: int = 10, offset: int = 0) -> list[dict]:
    """Search airports by name, city, IATA or ICAO code."""
    airports = _get("airports", {"search": search, "limit": limit, "offset": offset})
    return [
        {
            "name": a.get("airport_name"),
            "iata": a.get("iata_code"),
            "icao": a.get("icao_code"),
            "timezone": (a.get("timezone") or {}).get("timezone"),
        }
        for a in airports
    ]


@mcp.tool()
def list_airlines(search: str = "", limit: int = 10, offset: int = 0) -> list[dict]:
    """Search airlines by name or IATA/ICAO code."""
    airlines = _get("airlines", {"search": search, "limit": limit, "offset": offset})
    return [
        {
            "name": a.get("airline_name"),
            "iata": a.get("iata_code"),
            "icao": a.get("icao_code"),
            "country": a.get("country_name"),
        }
        for a in airlines
    ]


if __name__ == "__main__":
    mcp.run(transport="stdio")
