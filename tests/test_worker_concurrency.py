import asyncio
import contextlib
import pytest
from test_recall import make_backend


@pytest.mark.asyncio
async def test_recall_slow_job_does_not_block_other_jobs(tmp_path):
    _,service,_=make_backend(tmp_path)
    service.store.enqueue('slow',{'event':'test.slow'})
    service.store.enqueue('fast',{'event':'test.fast'})
    started,release,finished=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def process(job):
        if job['id']=='slow': started.set(); await release.wait()
        else: finished.set()
    service.process=process
    task=asyncio.create_task(service.worker())
    try:
        await asyncio.wait_for(started.wait(),2)
        await asyncio.wait_for(finished.wait(),1)
    finally:
        release.set(); task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
