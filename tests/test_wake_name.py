import pytest

from meeting_agent.models import SessionCreate
from meeting_agent.services import should_answer


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Alloy, what's our budget?", True),
        ("hey ALLOY when is the demo launch", True),
        ("Alloy tell us the plan", True),
        ("AI notetaker, what's our budget?", False),
        ("AI note taker, what's our budget?", False),
        ("Aloy's AI, what's our budget?", False),
        ("What's our budget?", False),
        ("Superalloy, what's our budget?", False),
        ("Hello Alloy", False),
    ],
)
def test_only_delegate_name_wakes_bot(text, expected):
    approved, _ = should_answer(text, agent_name="Alloy", owner_name="Aloy")
    assert approved is expected


def test_new_sessions_default_to_alloy():
    assert SessionCreate(title="Demo", owner_name="Aloy").agent_name == "Alloy"


def test_custom_name_and_manual_override_still_work():
    assert should_answer("Nova, when is launch?", agent_name="Nova", owner_name="Aloy")[0]
    assert not should_answer("Alloy, when is launch?", agent_name="Nova", owner_name="Aloy")[0]
    assert should_answer("When is launch?", agent_name="Alloy", owner_name="Aloy", force_answer=True)[0]
