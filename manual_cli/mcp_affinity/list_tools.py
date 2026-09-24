import asyncio

import httpx2._sse as _sse
from mcp import Client
from mcp.client.sse import sse_client

AFFINITY_MCP_URL = "http://localhost:6767/sse"


def _patch_lenient_sse_content_type() -> None:
    # Le serveur MCP local d'Affinity renvoie l'en-tête Content-Type en double
    # ("text/event-stream, text/event-stream"), ce que la vérification stricte
    # de httpx2 (égalité exacte) rejette. On assouplit la vérification pour
    # accepter "text/event-stream" comme l'une des valeurs, sans modifier le
    # package installé.
    def _lenient_check_content_type(self: _sse.EventSource) -> None:
        content_type, _, _ = self.response.headers.get("content-type", "").partition(";")
        values = {v.strip().lower() for v in content_type.split(",")}
        if "text/event-stream" not in values:
            raise _sse.SSEError(f"Expected response with content type 'text/event-stream', got {content_type.strip()!r}.")

    _sse.EventSource._check_content_type = _lenient_check_content_type


_patch_lenient_sse_content_type()


async def main():
    async with Client(sse_client(AFFINITY_MCP_URL)) as client:
        result = await client.list_tools()
        for tool in result.tools:
            print(f"Outil: {tool.name}")
            print(f"Description: {tool.description}")
            print(f"Paramètres: {tool.input_schema}")
            print("---")


asyncio.run(main())