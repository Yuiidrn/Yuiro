import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from yuiro.diary import DiaryStore, _SCHEMA
from yuiro.diary.media import upload, validate_assets, revise
from yuiro.diary.service import DiaryService
from yuiro.diary.session import DiarySession

PNG = bytes.fromhex('89504e470d0a1a0a') + b'test-fixture'


def test_existing_database_migrates_without_losing_text(tmp_path):
    path=tmp_path/'old.db'
    conn=sqlite3.connect(path)
    for sql in _SCHEMA: conn.execute(sql)
    conn.execute("INSERT INTO diaries(created_at,updated_at,raw_text,privacy) VALUES ('a','a','原文','local_only')")
    conn.commit();conn.close()
    store=DiaryStore(path)
    assert store.get(1)['raw_text']=='原文'
    assert store.get(1)['title']=='' and store.get(1)['revision']==1
    store.close()


def test_media_revision_restore_conflict_and_cascade(tmp_path):
    store=DiaryStore(tmp_path/'diary.db')
    asset=upload(store,'../photo.png',PNG)
    assert asset['name']=='photo.png'
    key=store.save(raw_text='old',title='标题',attachment_ids=[asset['id']])
    revise(store,key,revision=1,title='新标题',text='new',ids=[])
    old=json.loads(store.conn.execute('SELECT snapshot FROM diary_revisions').fetchone()[0])
    assert old['raw_text']=='old' and old['source_meta']['attachment_ids']==[asset['id']]
    assert store.search('新标题')[0]['id']==key
    with pytest.raises(ValueError):revise(store,key,revision=1,title='overwrite',text='bad',ids=[])
    assert store.get(key)['raw_text']=='new'
    revise(store,key,revision=2,title=old['title'],text=old['raw_text'],ids=old['source_meta']['attachment_ids'])
    assert store.get(key)['revision']==3
    assert len(store.conn.execute('SELECT * FROM diary_revisions').fetchall())==2
    store.conn.execute('DELETE FROM diaries WHERE id=?',(key,));store.conn.commit()
    assert not store.conn.execute('SELECT * FROM diary_assets').fetchall()
    assert not store.conn.execute('SELECT * FROM diary_revisions').fetchall()
    store.close()


def test_attachments_reject_unknown_other_entry_and_other_role(tmp_path):
    first=DiaryStore(tmp_path/'one.db');second=DiaryStore(tmp_path/'two.db')
    with pytest.raises(ValueError):upload(first,'photo.png',b'<script>alert(1)</script>')
    asset=upload(first,'x.png',PNG)
    with pytest.raises(ValueError):validate_assets(second,[asset['id']])
    key=first.save(raw_text='one',attachment_ids=[asset['id']])
    with pytest.raises(ValueError):first.save(raw_text='two',attachment_ids=[asset['id']])
    validate_assets(first,[asset['id']],key)
    with pytest.raises(ValueError):validate_assets(first,[asset['id']]*2,key)
    first.close();second.close()


@pytest.mark.asyncio
async def test_attachment_only_raw_save_and_no_llm(tmp_path):
    store=DiaryStore(tmp_path/'diary.db');service=DiaryService(store)
    service.deconstruct=AsyncMock(side_effect=AssertionError('must not call llm'))
    asset=upload(store,'x.png',PNG)
    session=DiarySession(service=service);session.start()
    result=await session.save_raw(metadata={'title':'照片','attachment_ids':[asset['id']]})
    assert result['ok'] and not session.active
    row=store.get(result['diary_id'])
    assert row['title']=='照片' and row['raw_text']==''
    service.deconstruct.assert_not_called();store.close()


@pytest.mark.asyncio
async def test_edit_shared_memory_replaces_old_and_failed_revoke_blocks(tmp_path):
    store=DiaryStore(tmp_path/'diary.db')
    texts=[]
    async def add(text,**kw):texts.append(text)
    async def forget(text):
        if text in texts:texts.remove(text)
        return 1
    memory=SimpleNamespace(retriever=SimpleNamespace(add=add),forget_text=forget)
    service=DiaryService(store,memory=memory)
    result=await service.submit('旧事情',privacy='shared',data={'title':'过去'})
    key=result['diary_id']
    await service.edit(key,revision=1,title='现在',text='新事情',attachment_ids=[])
    assert len(texts)==1 and '新事情' in texts[0] and '旧事情' not in texts[0]
    memory.forget_text=AsyncMock(side_effect=RuntimeError('offline'))
    with pytest.raises(ValueError):await service.edit(key,revision=2,title='失败',text='未保存',attachment_ids=[])
    assert store.get(key)['raw_text']=='新事情'
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('configured,supplied', [('test-only','test-only'),('dev-only-change-me',''),('','')])
async def test_media_api_requires_secret_and_role(tmp_path, configured, supplied):
    from yuiro.debug_api import router
    app=FastAPI();app.include_router(router)
    store=DiaryStore(tmp_path/'diary.db')
    app.state.diary_store=store;app.state.diary=DiaryService(store)
    app.state.app_config=SimpleNamespace(server=SimpleNamespace(shared_secret=configured),_character_id='hiyori')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        if configured == 'test-only':
            assert (await client.post('/api/diary/assets',content=PNG)).status_code==401
            wrong={'x-yuiro-secret':'incorrect','x-yuiro-character':'hiyori'}
            assert (await client.post('/api/diary/assets',content=PNG,headers=wrong)).status_code==401
            assert (await client.put('/api/diary/1',json={},headers=wrong)).status_code==401
        auth={'x-yuiro-secret':supplied,'x-yuiro-character':'hotaru'}
        assert (await client.post('/api/diary/assets',content=PNG,headers=auth)).status_code==409
        auth['x-yuiro-character']='hiyori'
        result=await client.post('/api/diary/assets?name=photo.png',content=PNG,headers=auth)
        assert result.status_code==200
        key=result.json()['asset']['id']
        response=await client.get('/api/diary/assets/'+key,headers=auth)
        assert response.content==PNG and response.headers['cache-control']=='no-store'
        entry=await app.state.diary.submit('初始正文',data={'title':'旅行','attachment_ids':[key]})
        diary_id=entry['diary_id']
        update={'revision':1,'title':'旅行补记','raw_text':'修改正文','attachment_ids':[key]}
        changed=await client.put(f'/api/diary/{diary_id}',headers=auth,json=update)
        assert changed.status_code==200 and changed.json()['revision']==2
        conflict=await client.put(f'/api/diary/{diary_id}',headers=auth,json=update)
        assert conflict.status_code==409
        detail=(await client.get(f'/api/diary/{diary_id}')).json()['diary']
        assert detail['attachments'][0]['id']==key and detail['title']=='旅行补记'
        history=(await client.get(f'/api/diary/{diary_id}/revisions',headers=auth)).json()['items']
        assert history[0]['title']=='旅行' and history[0]['raw_text']=='初始正文'
        assert history[0]['attachments'][0]['id']==key
        restore={**update,'revision':2,'title':history[0]['title'],'raw_text':history[0]['raw_text']}
        assert (await client.put(f'/api/diary/{diary_id}',headers=auth,json=restore)).json()['revision']==3
    store.close()
