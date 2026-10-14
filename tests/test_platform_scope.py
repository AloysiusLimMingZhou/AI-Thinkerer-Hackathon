import pytest
from fastapi import HTTPException
from meeting_agent.recall import validate_meeting_url
from test_api import make_client


def test_new_dispatch_accepts_only_google_meet():
    validate_meeting_url("https://meet.google.com/abc-defg-hij")
    for url in ["https://zoom.us/j/123", "https://teams.microsoft.com/l/meetup-join/x"]:
        with pytest.raises(HTTPException) as error:
            validate_meeting_url(url)
        assert error.value.status_code == 422


def test_removed_providers_are_not_active(tmp_path):
    client, _ = make_client(tmp_path)
    assert [item['provider'] for item in client.get('/platforms').json()] == ['google']
    for provider in ['slack', 'microsoft', 'zoom']:
        assert client.post(f'/integrations/{provider}/authorize').status_code == 422


def test_old_meeting_records_are_readable(tmp_path):
    client, _ = make_client(tmp_path)
    session = client.post('/sessions', json={
        'title': 'Historical', 'owner_name': 'Aloy', 'meeting_url': 'https://zoom.us/j/123'
    }).json()
    assert client.get('/sessions/' + session['id']).json()['title'] == 'Historical'
