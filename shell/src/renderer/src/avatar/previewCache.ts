/** 缩略图使用IndexedDB，避免同步localStorage大图阻塞界面。失败仅影响缓存。 */
let database:Promise<IDBDatabase|null>|undefined
function open(){return database??=new Promise<IDBDatabase|null>(resolve=>{
  let settled=false
  const timer=setTimeout(()=>finish(null),2000)
  const finish=(db:IDBDatabase|null)=>{
    if(settled){db?.close();return}
    settled=true;clearTimeout(timer);resolve(db)
  }
  const r=indexedDB.open('yuiro-avatar-previews',1)
  r.onupgradeneeded=()=>r.result.createObjectStore('images')
  r.onsuccess=()=>{r.result.onversionchange=()=>{r.result.close();database=undefined};finish(r.result)}
  r.onerror=()=>finish(null)
  r.onblocked=()=>finish(null)
})}
export async function readPreview(key:string):Promise<string>{
  try{const db=await open();if(!db)return '';return await new Promise<string>(resolve=>{
    const timer=setTimeout(()=>resolve(''),2000)
    const finish=(value:string)=>{clearTimeout(timer);resolve(value)}
    const t=db.transaction('images'),r=t.objectStore('images').get(key)
    r.onsuccess=()=>finish(typeof r.result==='string'?r.result:'');r.onerror=()=>finish('')
    t.onabort=()=>finish('');t.onerror=()=>finish('')
  })}catch{return ''}
}
export async function writePreview(key:string,image:string):Promise<void>{
  if(!image)return
  try{const db=await open();if(!db)return;await new Promise<void>(resolve=>{
    const timer=setTimeout(resolve,2000)
    const finish=()=>{clearTimeout(timer);resolve()}
    const t=db.transaction('images','readwrite');t.objectStore('images').put(image,key)
    t.oncomplete=finish;t.onerror=finish;t.onabort=finish
  })}catch{/* 存储不可用不阻断动态预览 */}
}
