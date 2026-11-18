"""One stable public asset URL; no private state or directory is exposed."""
from pathlib import Path
from aiohttp import web
from homeassistant.components.http import HomeAssistantView


class XparkleCardView(HomeAssistantView):
    url = "/xparkle_rvlevel/xparkle-card.js"
    name = "xparkle_rvlevel:card"
    requires_auth = False

    async def get(self, request):
        return web.FileResponse(Path(__file__).parent / "frontend" / "xparkle-card.js",
            headers={"Cache-Control": "no-store", "Content-Type": "text/javascript; charset=utf-8"})

    async def head(self, request):
        return await self.get(request)
