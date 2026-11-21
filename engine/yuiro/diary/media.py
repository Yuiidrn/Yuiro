"""角色日记库内的附件与修订；不接受客户端文件路径。"""
import json
import time
from uuid import uuid4

MAX_BYTES = 20 * 1024 * 1024
MAX_ASSETS = 8


def sniff(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')): return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp'
    if data.startswith(b'RIFF') and data[8:12] == b'WAVE': return 'audio/wav'
    if data.startswith(b'ID3') or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'): return 'audio/mpeg'
    if data.startswith(b'OggS'): return 'audio/ogg'
    if data[4:8] == b'ftyp': return 'video/mp4'
    if data.startswith(b'\x1aE\xdf\xa3'): return 'video/webm'
    raise ValueError('不支持的媒体格式，请选择 PNG/JPEG/GIF/WebP、WAV/MP3/OGG 或 MP4/WebM')


def upload(store, name: str, data: bytes) -> dict:
    if not data or len(data) > MAX_BYTES:
        raise ValueError('附件须非空且不超过20MB')
    mime = sniff(data)
    store.conn.execute('DELETE FROM diary_assets WHERE diary_id IS NULL AND created_at < ?', (time.time()-86400,))
    staging = store.conn.execute('SELECT COALESCE(SUM(length(data)),0) FROM diary_assets WHERE diary_id IS NULL').fetchone()[0]
    if staging + len(data) > MAX_BYTES * MAX_ASSETS:
        raise ValueError('待保存附件过多，请先保存记录或移除附件')
    key = uuid4().hex
    clean_name = name.replace('\\','/').rsplit('/',1)[-1][:180] or '附件'
    store.conn.execute('INSERT INTO diary_assets VALUES (?,?,?,?,?,NULL)', (key,clean_name,mime,data,time.time()))
    store.conn.commit()
    return {'id':key,'name':clean_name,'mime':mime,'size':len(data)}


def validate_assets(store, ids, diary_id=None):
    if not isinstance(ids,list) or len(ids)>MAX_ASSETS or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):
        raise ValueError('每篇最多8个附件，附件不可重复')
    for key in ids:
        row=store.conn.execute('SELECT diary_id FROM diary_assets WHERE id=?',(key,)).fetchone()
        if row is None or row[0] not in (None,diary_id):
            raise ValueError('附件已失效或不属于本篇记录')


def assets(store, ids):
    result=[]
    for key in ids:
        row=store.conn.execute('SELECT id,name,mime,length(data) AS size FROM diary_assets WHERE id=?',(key,)).fetchone()
        if row: result.append(dict(row))
    return result


def revise(store, diary_id, *, revision, title, text, ids):
    validate_assets(store, ids, diary_id)
    row=store.get(diary_id)
    if not row or row['revision']!=revision:
        raise ValueError('记录已被更新，请重新打开后再编辑；本地修改尚未丢弃')
    meta=dict(row['source_meta']);meta['attachment_ids']=ids
    with store.conn:
        store.conn.execute('INSERT INTO diary_revisions VALUES (?,?,?)',(diary_id,revision,json.dumps(row,ensure_ascii=False)))
        result=store.conn.execute("UPDATE diaries SET title=?,raw_text=?,polished_text=?,summary=?,closing_review='',mood_tags='[]',topics='[]',entities='[]',followup_question='',source_meta=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?",
            (title[:160],text,text,' '.join(text.split())[:120],json.dumps(meta,ensure_ascii=False),time.strftime('%Y-%m-%dT%H:%M:%S'),diary_id,revision))
        if result.rowcount!=1: raise ValueError('记录版本冲突')
        store.conn.execute('DELETE FROM diary_tags WHERE diary_id=?',(diary_id,))
        for key in ids: store.conn.execute('UPDATE diary_assets SET diary_id=? WHERE id=?',(diary_id,key))
    return store.get(diary_id)
