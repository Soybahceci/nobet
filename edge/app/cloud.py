"""
NÖBET Kenar — bulut istemcisi
==============================
Mimari: §2.4, §3.1, §3.1b, §3.2

Tek yönlü: kenar buluta **giden** bağlantı açar. Kurumun modeminde port
açılmaz, gelen bağlantı beklenmez.

Jeton `Authorization: Bearer` ile gider ve bulut kurumu **yalnızca ondan**
belirler — gövdedeki `node_key` bir kurum seçmez, o kurum içinde aranır.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx

log = logging.getLogger("edge.cloud")

# Bulut yavaşsa kuyruk beklesin, ama sonsuza kadar değil: askıda kalan bir
# istek senkron döngüsünü tümden durdurur.
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class CloudError(Exception):
    """Ağ/sunucu hatası — yeniden denenebilir."""


class AuthError(CloudError):
    """Jeton geçersiz — yeniden denemek düzeltmez, insan müdahalesi gerek."""


class Cloud:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise AuthError("kenar jetonu yok — once eslestirme yapilmali")
        return {"Authorization": f"Bearer {self.token}"}

    async def _post(self, path: str, payload: dict[str, Any],
                    auth: bool = True) -> dict[str, Any]:
        headers = self._headers() if auth else {}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                r = await c.post(f"{self.base}{path}", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise CloudError(f"ag hatasi: {exc}") from exc

        if r.status_code == 401:
            raise AuthError("bulut jetonu reddetti")
        if r.status_code >= 400:
            raise CloudError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    # --- eşleştirme --------------------------------------------------------
    async def pair(self, code: str) -> dict[str, Any]:
        return await self._post("/api/v1/edge/pair", {"code": code}, auth=False)

    # --- yukarı: olaylar ---------------------------------------------------
    async def push_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Toplu gönderim. Yanıt üç kova: `accepted`, `duplicate`, `rejected`.

        ⚠️ Çağıran, `rejected` kovasını **mutlaka** işlemeli. Kuyrukta
        bırakılan kalıcı ret, arkasındaki her şeyi sonsuza kadar tıkar.
        """
        return await self._post("/api/v1/edge/events", {"events": events})

    # --- aşağı: kart kopyası ----------------------------------------------
    async def fetch_cards(self, since: int) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                r = await c.get(
                    f"{self.base}/api/v1/edge/credentials",
                    params={"since": since}, headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise CloudError(f"ag hatasi: {exc}") from exc
        if r.status_code == 401:
            raise AuthError("bulut jetonu reddetti")
        if r.status_code >= 400:
            raise CloudError(f"HTTP {r.status_code}")
        return r.json()

    # --- sağlık ------------------------------------------------------------
    async def heartbeat(self, queue_depth: int, dead_letters: int,
                        card_version_seen: int, agent_version: str) -> dict[str, Any]:
        return await self._post("/api/v1/edge/heartbeat", {
            "agent_version": agent_version,
            "queue_depth": queue_depth,
            "dead_letter_count": dead_letters,
            "card_version_seen": card_version_seen,
            "edge_time": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
