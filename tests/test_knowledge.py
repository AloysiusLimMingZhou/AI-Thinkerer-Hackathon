import io
import zipfile
import pytest
from meeting_agent.knowledge import KnowledgeService, bounded_extract, chunk_segments, extract_document
from meeting_agent.repository import SQLiteRepository
from meeting_agent.models import SessionCreate, ContextNoteCreate


def test_chunks_preserve_overlap_and_source_locator():
    chunks=chunk_segments('source','file','brief','brief.txt',[('page 2','x'*4000)])
    assert len(chunks[0].text)==2000
    assert chunks[0].text[-200:]==chunks[1].text[:200]
    assert 'page 2' in chunks[0].locator
    assert chunks[0].filename=='brief.txt'


def test_old_notes_backfill_once_and_unrelated_search_is_empty(tmp_path):
    repo=SQLiteRepository(tmp_path/'old.db')
    sid=repo.create_session(SessionCreate(title='Launch',owner_name='Aloy')).id
    repo.add_context(sid,[ContextNoteCreate(title='Launch',content='The launch is Friday.')])
    knowledge=KnowledgeService(repo)
    assert knowledge.search(sid,'What is the cafeteria schedule?') == []
    assert 'Friday' in knowledge.search(sid,'When is launch?')[0].text
    assert len(KnowledgeService(repo).list_sources(sid)) == 1


def test_extraction_process_timeout_is_terminated():
    with pytest.raises(ValueError,match='timed out'):
        bounded_extract('small.txt',b'Friday',timeout=0)


def test_blank_pdf_and_oversized_pdf_reject_or_produce_no_text():
    from pypdf import PdfWriter
    writer=PdfWriter(); writer.add_blank_page(width=100,height=100)
    data=io.BytesIO(); writer.write(data)
    assert not any(text.strip() for _,text in extract_document('blank.pdf',data.getvalue()))
    for _ in range(300): writer.add_blank_page(width=100,height=100)
    data=io.BytesIO(); writer.write(data)
    with pytest.raises(ValueError,match='300'):
        extract_document('too-many.pdf',data.getvalue())


def test_docx_archive_expansion_limit_checked_before_xml():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive: archive.writestr('word/document.xml','x')
    body=bytearray(data.getvalue()); central=body.index(b'PK\x01\x02')
    body[central+24:central+28]=(51*1024*1024).to_bytes(4,'little')
    with pytest.raises(ValueError,match='expanded'):
        extract_document('large.docx',bytes(body))
