"""The suite cannot reach a guidance provider, and it is structure that stops it.

There is no ``-m 'not llm_live'`` in ``addopts`` and no environment guard, because both are
things a future edit can quietly step around. What actually holds is narrower: a provider is
constructed only when the feature is *enabled* and a key *resolves*, and the default is
neither. With no provider there is no object to call, so the way to accidentally issue a live
request is to write a test that deliberately builds one.

These assertions pin that construction rule at the two places it is made — the factory, and
``create_app`` — so the guarantee is checked rather than assumed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.deps import GUIDANCE_SERVICE_ATTR, LLM_PROVIDER_ATTR
from tracker.app import create_app
from tracker.config.settings import LlmSettings, Settings
from tracker.content.loader import Content
from tracker.content.validate import load_and_validate
from tracker.db.models import Base
from tracker.db.session import build_engine, build_session_factory
from tracker.integrations.llm import build_provider

CONTENT_ROOT = Path(__file__).parent.parent.parent.parent / "content"

#: Never sent anywhere. Present only so a test can prove that having a key is not enough.
PLACEHOLDER_KEY = "sk-ant-not-a-real-key"


@pytest.fixture(scope="session")
def corpus() -> Content:
    return load_and_validate(CONTENT_ROOT)


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_the_shipped_default_is_disabled() -> None:
    """D14's promise starts here: an unconfigured install has the feature off."""
    assert LlmSettings().enabled is False


def test_a_key_alone_does_not_switch_the_feature_on() -> None:
    """A developer with ``ANTHROPIC_API_KEY`` exported must not silently start paying.

    Both conditions are required, and this is the one that would otherwise be easy to lose:
    a key is permission to spend, not an instruction to.
    """
    assert build_provider(LlmSettings(), api_key=PLACEHOLDER_KEY) is None


def test_create_app_builds_no_provider_by_default(
    factory: sessionmaker[Session],
    corpus: Content,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole application, built the way every test builds it, holds no client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER_KEY)
    settings = Settings(bind_address="127.0.0.1", api_token="token")

    app = create_app(settings, session_factory=factory, content=corpus, mount_ui=False)

    assert getattr(app.state, LLM_PROVIDER_ATTR) is None
    assert getattr(app.state, GUIDANCE_SERVICE_ATTR).enabled is False


def test_an_enabled_but_unkeyed_install_still_builds_nothing(
    factory: sessionmaker[Session],
    corpus: Content,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching the feature on without a key is a disabled feature, not a crash."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(
        bind_address="127.0.0.1",
        api_token="token",
        integrations={"llm": {"enabled": True}},
    )

    app = create_app(settings, session_factory=factory, content=corpus, mount_ui=False)

    assert getattr(app.state, LLM_PROVIDER_ATTR) is None
    assert getattr(app.state, GUIDANCE_SERVICE_ATTR).enabled is False


def test_an_injected_provider_is_the_only_way_a_test_gets_one(
    factory: sessionmaker[Session], corpus: Content
) -> None:
    """And an injected one is a double, so it reaches no network either."""

    class Nothing:
        @property
        def model(self) -> str:
            return "stub"

        def generate(self, prompt: object) -> object:  # pragma: no cover — never called
            raise AssertionError("this double exists to be counted, not called")

        def close(self) -> None:
            return None

    settings = Settings(bind_address="127.0.0.1", api_token="token")
    app = create_app(
        settings,
        session_factory=factory,
        content=corpus,
        guidance_provider=Nothing(),  # type: ignore[arg-type]
        mount_ui=False,
    )

    assert getattr(app.state, GUIDANCE_SERVICE_ATTR).enabled is True
