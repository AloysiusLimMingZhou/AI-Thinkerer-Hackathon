import importlib.util
from pathlib import Path
import pytest
from meeting_agent.meeting_models import BrainAnswer,AnswerEvidence
from test_api import FakeVoice


@pytest.mark.asyncio
async def test_opt_in_eval_consumes_structured_answers_without_provider_calls(monkeypatch,capsys,tmp_path):
    monkeypatch.setenv('MEETING_AGENT_DB',str(tmp_path/'eval.db'))
    path=Path(__file__).parents[1]/'scripts/eval_conversation.py'
    spec=importlib.util.spec_from_file_location('eval_live',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    class Brain:
        async def answer(self,session,question,history,chunks):
            assert chunks[0].text and chunks[0].source_id
            text='Friday' if 'launch' in question else 'Jamie' if 'checklist' in question else 'Budget is undecided' if 'budget?' in question else None
            return BrainAnswer(kind='supported' if text else 'unknown',text=text or '',evidence=[AnswerEvidence(chunk_id=chunks[0].id,quote=chunks[0].text)] if text else [])
    monkeypatch.setattr(module,'OpenAIBrain',lambda settings,budget=None:Brain())
    monkeypatch.setattr(module,'ElevenLabsVoice',lambda settings,budget=None:FakeVoice())
    await module.main()
    assert 'Friday' in capsys.readouterr().out
