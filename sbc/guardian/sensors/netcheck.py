"""Cek koneksi internet (modem 4G) dengan koneksi TCP ringan."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def check_once(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def run(cfg, state, bus) -> None:
    last = None
    while True:
        n = cfg.section("network")
        ok = await check_once(n.get("check_host", "1.1.1.1"), int(n.get("check_port", 53)))
        state.update("net", internet=ok, checked=asyncio.get_running_loop().time())
        if ok != last:
            log.info("internet %s", "tersedia" if ok else "PUTUS")
            bus.publish("internet", ok)
            last = ok
        await asyncio.sleep(float(n.get("check_interval_s", 20)))
