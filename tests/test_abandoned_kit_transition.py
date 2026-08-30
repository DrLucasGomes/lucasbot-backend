import recovery_state_exclusivity as state


class FakeResponse:
    def __init__(self, status_code=204):
        self.status_code = status_code


def test_abandoned_entry_and_cleanup_are_both_required(monkeypatch):
    posts = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_ABANDONO_ID", "abandon")
    monkeypatch.setenv("TAG_RECUPERACAO_VIDEO_ID", "video")

    def fake_post(url, **kwargs):
        posts.append((url, kwargs))
        return FakeResponse(204)

    monkeypatch.setattr(state.requests, "post", fake_post)

    assert state.garantir_tag_estado_kit("lead@example.com", "abandoned") is True
    assert state.convergir_tags_kit("lead@example.com", "abandoned") is True
    assert [url for url, _ in posts] == [
        f"{state.KIT_BASE_URL}/tags/abandon/subscribe",
        f"{state.KIT_BASE_URL}/tags/video/unsubscribe",
    ]
    assert all(call[1]["json"]["email"] == "lead@example.com" for call in posts)


def test_abandoned_cleanup_fails_closed_if_post_click_tag_missing(monkeypatch):
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_ABANDONO_ID", "abandon")
    monkeypatch.delenv("TAG_RECUPERACAO_VIDEO_ID", raising=False)
    monkeypatch.setattr(state.requests, "post", lambda *args, **kwargs: FakeResponse(204))

    assert state.garantir_tag_estado_kit("lead@example.com", "abandoned") is True
    assert state.convergir_tags_kit("lead@example.com", "abandoned") is False
