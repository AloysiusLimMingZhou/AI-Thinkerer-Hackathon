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
        ("Hello Alloy", True),
        ("Alloy", False),
        ("Alloy, will you explain the plan?", True),
        ("Alloy is a guy by the way", False),
        ("Can you tell Alloy that?", False),
        ("What does Alloy think?", False),
        ("What do you think, Alloy?", True),
        ("Alloy, can you tell Aloy the budget changed?", True),
        ("hi aloy what is today's meeting about", True),
        ("Can you tell Aloy that?", False),
        ("Aloy is a guy", False),
    ],
)
def test_only_delegate_name_wakes_bot(text, expected):
    approved, _ = should_answer(text, agent_name="Alloy", owner_name="Aloy")
    assert approved is expected


def test_new_sessions_default_to_alloy():
    assert SessionCreate(title="Demo", owner_name="Aloy").agent_name == "Alloy"


def test_custom_name_and_manual_override_still_work():
    assert should_answer("Nova, when is launch?", agent_name="Nova", owner_name="Aloy")[
        0
    ]
    assert not should_answer(
        "Alloy, when is launch?", agent_name="Nova", owner_name="Aloy"
    )[0]
    assert should_answer(
        "When is launch?", agent_name="Alloy", owner_name="Aloy", force_answer=True
    )[0]
