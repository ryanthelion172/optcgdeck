import httpx
import pytest
from fastapi.testclient import TestClient

from app import images
from app.main import app

PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
def fake_web(tmp_path, monkeypatch):
    """Replaces the internet with a handler and the cache with a temp folder."""
    calls = []

    def use(handler):
        def record(request):
            calls.append(request)
            return handler(request)

        monkeypatch.setattr(images, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(
            images, "_client", httpx.AsyncClient(transport=httpx.MockTransport(record))
        )
        return calls

    return use


def test_downloads_once_then_serves_from_cache(fake_web):
    calls = fake_web(lambda r: httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    client = TestClient(app)

    first = client.get("/api/cards/OP01-001/image")
    assert first.status_code == 200
    assert first.content == PNG
    assert first.headers["content-type"] == "image/png"
    assert "en.onepiece-cardgame.com" in str(calls[0].url)

    second = client.get("/api/cards/OP01-001/image")
    assert second.content == PNG
    assert len(calls) == 1  # served from the cache the second time


def test_falls_back_to_second_source(fake_web):
    def handler(request):
        if "onepiece-cardgame" in request.url.host:
            return httpx.Response(403, text="Forbidden", headers={"content-type": "text/html"})
        return httpx.Response(200, content=b"RIFFwebp", headers={"content-type": "image/webp"})

    calls = fake_web(handler)
    resp = TestClient(app).get("/api/cards/OP01-001/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert "limitlesstcg" in str(calls[1].url)


def test_502_when_no_source_works(fake_web):
    fake_web(lambda r: httpx.Response(404))
    assert TestClient(app).get("/api/cards/OP01-001/image").status_code == 502


def test_unknown_card_404(fake_web):
    fake_web(lambda r: httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    assert TestClient(app).get("/api/cards/XX99-999/image").status_code == 404


def test_alternate_arts_are_not_downloaded(fake_web):
    calls = fake_web(lambda r: httpx.Response(200, content=PNG, headers={"content-type": "image/png"}))
    assert TestClient(app).get("/api/cards/OP01-001_p1/image").status_code == 404
    assert calls == []


def test_simultaneous_requests_download_once(fake_web):
    import asyncio

    async def slow(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    calls = fake_web(slow)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(*[client.get("/api/cards/OP01-016/image") for _ in range(5)])

    responses = asyncio.run(run())
    assert [r.status_code for r in responses] == [200] * 5
    assert all(r.content == PNG for r in responses)
    assert len(calls) == 1


def test_each_regions_site_gets_its_own_referer():
    from app.images import referer_for

    assert referer_for("https://asia-en.onepiece-cardgame.com/images/cardlist/card/OP03-055_p1.png") == (
        "https://asia-en.onepiece-cardgame.com/cardlist/"
    )
    assert referer_for("https://www.onepiece-cardgame.com/images/x.png") == "https://www.onepiece-cardgame.com/cardlist/"
    assert referer_for("https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/x.webp") == "https://en.onepiece-cardgame.com/cardlist/"
