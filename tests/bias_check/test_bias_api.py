import httpx, pytest
from core.main import app
from engines.responsibility.bias_check.bias_detector import BiasDetector
from tests.bias_check.test_bias_detector import Embeddings, Classifier

@pytest.fixture
def anyio_backend(): return "asyncio"

@pytest.mark.anyio
async def test_bias_api_explicit_and_validation(monkeypatch):
    import api.routes.responsibility as routes
    monkeypatch.setattr(routes, "get_bias_detector", lambda: BiasDetector(embedding_model=Embeddings(), classifier=Classifier()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response=await client.post("/responsibility/bias/scan",json={"text":"Male candidates should be preferred because men are better leaders."})
        missing=await client.post("/responsibility/bias/scan",json={})
        invalid=await client.post("/responsibility/bias/scan",json={"text":42})
    assert response.status_code==200 and response.json()["detected"] is True
    assert missing.status_code==422 and invalid.status_code==422

@pytest.mark.anyio
async def test_bias_api_subtle_bias(monkeypatch):
    import api.routes.responsibility as routes
    monkeypatch.setattr(routes, "get_bias_detector", lambda: BiasDetector(embedding_model=Embeddings(), classifier=Classifier()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response=await client.post("/responsibility/bias/scan",json={"text":"For leadership roles I would lean toward men because they tend to handle pressure more effectively."})
    assert response.status_code==200 and response.json()["detected"] is True


@pytest.mark.anyio
async def test_bias_api_safe_response_and_invalid_target(monkeypatch):
    import api.routes.responsibility as routes
    monkeypatch.setattr(routes, "get_bias_detector", lambda: BiasDetector(embedding_model=Embeddings(), classifier=Classifier()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        safe = await client.post("/responsibility/bias/scan", json={"text": "Candidate A has five years of Java experience."})
        invalid = await client.post("/responsibility/bias/scan", json={"text": "hello", "scan_target": "prompt"})
    assert safe.status_code == 200
    assert safe.json()["detected"] is False
    assert invalid.status_code == 422

@pytest.mark.anyio
async def test_bias_api_model_failure_is_503(monkeypatch):
    import api.routes.responsibility as routes
    from engines.responsibility.bias_check.bias_detector import BiasDetectorError
    monkeypatch.setattr(routes,"get_bias_detector",lambda: (_ for _ in ()).throw(BiasDetectorError()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response=await client.post("/responsibility/bias/scan",json={"text":"hello"})
    assert response.status_code==503
