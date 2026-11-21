import asyncio,subprocess,json,os
from pathlib import Path
exec(Path('scripts/diag/appearance_thumbnails_live.py').read_text(encoding='utf-8-sig').split('async def main():')[0])
async def main():
 output=Path(os.environ.get('YUIRO_BARGE_OUTPUT','docs/plan/avatar-barge-in-user-live.json'))
 page=next(p for p in pages() if 'index.html' in p['url'])
 async def config(c,e,value=None):
  return await e("(async()=>{const h={'Content-Type':'application/json','x-yuiro-secret':await window.yuiro.getEngineSecret(),'x-yuiro-character':localStorage.getItem('yuiro-active-character')||'hotaru'};const d=await(await fetch('http://127.0.0.1:8200/api/config',{headers:h})).json();"+("return {role:d.character.active_id,revision:d.character.revision,barge:d.sections.vad.barge_in_enabled}" if value is None else "const r=await fetch('http://127.0.0.1:8200/api/config',{method:'PUT',headers:h,body:JSON.stringify({character_id:d.character.active_id,character_revision:d.character.revision,patch:{vad:{barge_in_enabled:"+json.dumps(value)+"}}})});return {status:r.status,ok:r.ok}")+"})()")
 before=await connect(page,config);assert before['role']=='hotaru',before
 print('ORIGINAL_BARGE',before['barge'],flush=True)
 try:
  changed=await connect(page,lambda c,e:config(c,e,True));assert changed['ok'],changed
  await asyncio.sleep(3)
  subprocess.run([str(Path('.env-local/engine-venv2/Scripts/python.exe').resolve()),'scripts/diag/avatar_microphone_live.py'],check=True)
  evidence=json.loads(Path('docs/plan/avatar-microphone-live.json').read_text(encoding='utf-8'));evidence['test']='real user barge-in, temporary enabled setting';output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
 finally:
  restored=await connect(page,lambda c,e:config(c,e,before['barge']));assert restored['ok'],restored
  readback=await connect(page,config);assert readback['barge']==before['barge'],readback
  if 'evidence' in locals():
   evidence['restoredConfig']=readback
   output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
  print('RESTORED_BARGE',before['barge'],flush=True)
asyncio.run(main())
