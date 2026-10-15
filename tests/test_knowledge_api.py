from io import BytesIO
import pytest
from test_api import make_client


def setup(tmp_path):
    client, _ = make_client(tmp_path)
    sid = client.post('/sessions', json={'title':'Launch', 'owner_name':'Aloy'}).json()['id']
    return client, sid


def test_text_and_utf8_file_are_visible_and_duplicate_is_idempotent(tmp_path):
    client, sid = setup(tmp_path)
    url = f'/sessions/{sid}/knowledge'
    response = client.post(url, data={'text':'The launch is Friday.'}, files={'files':('brief.md', 'Budget approved: RM500. Café.'.encode(), 'text/markdown')})
    assert response.status_code == 201, response.text
    sources = client.get(url).json()
    assert len(sources) == 2
    assert any('Café' in item['preview'] and item['filename']=='brief.md' for item in sources)
    assert client.post(url, files={'files':('renamed.md', 'Budget approved: RM500. Café.'.encode(), 'text/plain')}).json()['duplicates']
    assert len(client.get(url).json()) == 2


@pytest.mark.parametrize('filename,body', [('bad.pdf',b'not PDF'),('secret.pdf',b'%PDF-broken'),('image.png',b'png'),('bad.txt',b'\xff'),('empty.txt',b' ')])
def test_invalid_batch_is_atomic(tmp_path, filename, body):
    client, sid = setup(tmp_path)
    response=client.post(f'/sessions/{sid}/knowledge',files=[('files',('valid.txt',b'Launch Friday','text/plain')),('files',(filename,body,'application/octet-stream'))])
    assert response.status_code == 422
    assert client.get(f'/sessions/{sid}/knowledge').json() == []


def test_file_count_size_and_unknown_session(tmp_path):
    client, sid=setup(tmp_path)
    files=[('files',(f'{i}.txt',b'facts','text/plain')) for i in range(6)]
    assert client.post(f'/sessions/{sid}/knowledge',files=files).status_code == 413
    assert client.post(f'/sessions/{sid}/knowledge',files={'files':('huge.txt',b'x'*(10*1024*1024+1),'text/plain')}).status_code == 413
    assert client.get('/sessions/missing/knowledge').status_code == 404


def test_existing_json_notes_are_listed(tmp_path):
    client,sid=setup(tmp_path)
    client.post(f'/sessions/{sid}/context',json={'notes':[{'title':'Calendar copy','source':'briefing','content':'Launch Friday.'}]})
    assert client.get(f'/sessions/{sid}/knowledge').json()[0]['preview'] == 'Launch Friday.'


def test_legacy_context_cannot_bypass_meeting_limit(tmp_path):
    client,sid=setup(tmp_path)
    notes=[{'title':str(i),'content':'x'*99_999+str(i)} for i in range(10)]
    assert client.post(f'/sessions/{sid}/context',json={'notes':notes}).status_code == 201
    assert client.post(f'/sessions/{sid}/context',json={'notes':[{'title':'extra','content':'over the limit'}]}).status_code == 413


def test_request_size_is_checked_before_multipart(tmp_path):
    client,sid=setup(tmp_path)
    response=client.post(f'/sessions/{sid}/knowledge',content=b'ignored',headers={'Content-Length':str(23*1024*1024)})
    assert response.status_code == 413


def test_pdf_docx_extract_real_text_and_reject_encrypted(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    from docx import Document
    writer=PdfWriter(); page=writer.add_blank_page(width=300,height=200)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 20 100 Td (Launch on Friday) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    pdf=BytesIO(); writer.write(pdf)
    document=Document(); document.add_paragraph('Budget is RM500'); doc=BytesIO(); document.save(doc)
    client,sid=setup(tmp_path)
    response=client.post(f'/sessions/{sid}/knowledge',files=[('files',('brief.pdf',pdf.getvalue(),'application/pdf')),('files',('brief.docx',doc.getvalue(),'application/octet-stream'))])
    assert response.status_code == 201, response.text
    sources=client.get(f'/sessions/{sid}/knowledge').json()
    assert any('Launch on Friday' in s['preview'] for s in sources)
    assert any('Budget is RM500' in s['preview'] for s in sources)
    writer.encrypt('password'); encrypted=BytesIO(); writer.write(encrypted)
    assert client.post(f'/sessions/{sid}/knowledge',files={'files':('locked.pdf',encrypted.getvalue(),'application/pdf')}).status_code == 422
