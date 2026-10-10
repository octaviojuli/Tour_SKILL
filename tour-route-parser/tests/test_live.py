"""The live call path: the only tests that exercise the installed SDK against a real endpoint.

Every other test runs on fakes, which is how an SDK that rejected our arguments shipped green
(anthropic 1.x dropped ``temperature`` from ``messages.create``; ``llm.py`` turned the TypeError
into ``ModelError`` and the run "succeeded" with 0 model calls).

- ``test_sdk_accepts_what_llm_sends`` runs everywhere, offline: the installed SDK must accept
  every argument ``Model.ask`` passes.
- ``test_live_structured_call`` (marker ``live``) makes one real call through ``Model.ask``. It
  reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ROUTE_KIT_MODEL from the environment, or from
  the env file named by ROUTE_KIT_ENV. Without them it skips, unless ROUTE_KIT_REQUIRE_LIVE=1
  (set in CI), where missing credentials fail the run instead of hiding it.

    python -m pytest tests -m live                       # live only
    ROUTE_KIT_ENV=/private/model.env python -m pytest tests -m live
"""

import inspect
import os
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_kit.llm import Model, load_env  # noqa: E402

# The keyword arguments Model.ask passes to client.messages.create.
SENT = ("model", "max_tokens", "temperature", "thinking", "system", "messages", "tools", "tool_choice")


def test_sdk_accepts_what_llm_sends():
    import anthropic

    source = inspect.getsource(Model.ask)
    for name in SENT:  # the list above must stay in step with llm.py
        assert f"{name}=" in source, f"Model.ask no longer sends {name}; update SENT"
    params = inspect.signature(anthropic.Anthropic(api_key="x").messages.create).parameters
    takes_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    missing = [name for name in SENT if name not in params and not takes_any]
    assert not missing, (
        f"anthropic {anthropic.__version__} messages.create() does not accept {missing}; "
        "pyproject pins anthropic<1.0 for this reason"
    )


class Echo(BaseModel):
    city: str
    days: int


@pytest.mark.live
def test_live_structured_call(tmp_path):
    env_file = os.environ.get("ROUTE_KIT_ENV")
    settings = load_env(Path(env_file) if env_file else None)
    configured = settings.get("ANTHROPIC_API_KEY") and (
        settings.get("ROUTE_KIT_MODEL") or settings.get("TOUR_MODEL")
    )
    if not configured:
        message = "no model credentials (ANTHROPIC_API_KEY + ROUTE_KIT_MODEL, or ROUTE_KIT_ENV)"
        if os.environ.get("ROUTE_KIT_REQUIRE_LIVE") == "1":
            pytest.fail(message + " but ROUTE_KIT_REQUIRE_LIVE=1")
        pytest.skip(message)
    model = Model(settings, tmp_path / "cache")  # isolated cache: this call is never a cache hit
    answer = model.ask(
        "从输入的线路名称里读出出发城市和天数。仅调用 submit_result。",
        {"name": "厦门出发 ACME 古镇一日游"},
        Echo,
        max_tokens=200,
    )
    assert isinstance(answer, Echo) and answer.city and answer.days >= 1
    assert model.calls == 1 and model.cached == 0  # it went over the wire, once
