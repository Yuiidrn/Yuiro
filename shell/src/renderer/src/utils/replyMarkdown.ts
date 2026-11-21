import { marked } from 'marked'
import DOMPurify from 'dompurify'

/** 只渲染文本排版；不加载图片、HTML 控件或执行模型返回的代码。 */
export function replyMarkdown(text:string):string {
  const html=marked.parse(text,{async:false,gfm:true,breaks:true}) as string
  const safe=DOMPurify.sanitize(html,{ALLOWED_TAGS:['p','br','strong','em','del','code','pre','blockquote','ul','ol','li','h1','h2','h3','h4','hr','a','table','thead','tbody','tr','th','td'],ALLOWED_ATTR:['href','title','start'],ALLOW_DATA_ATTR:false})
  const doc=new DOMParser().parseFromString(safe,'text/html')
  for(const a of doc.querySelectorAll('a')){
    const url=a.getAttribute('href')??''
    if(!/^https?:\/\//i.test(url))a.removeAttribute('href')
  }
  return doc.body.innerHTML
}
