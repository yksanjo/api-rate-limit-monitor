from monitor import RateLimitMonitor


class _Resp:
    headers = {"X-RateLimit-Remaining": "10", "X-RateLimit-Limit": "100"}

    def raise_for_status(self):
        return None


def test_add_and_remove_api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = RateLimitMonitor()
    m.add_api("github", "https://api.github.com/rate_limit", {}, 0.9)
    assert "github" in m.apis
    m.remove_api("github")
    assert "github" not in m.apis


def test_check_rate_limit_parses_headers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = RateLimitMonitor()
    monkeypatch.setattr("monitor.requests.get", lambda *args, **kwargs: _Resp())
    out = m.check_rate_limit("x", {"endpoint": "https://example.com", "headers": {}})
    assert out is not None
    assert out["remaining"] == 10
    assert out["limit"] == 100
