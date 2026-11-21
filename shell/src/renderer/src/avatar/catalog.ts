/** 资源分类只描述可识别语义，未知文件保留待分类，不臆造含义。 */
export function resourceCategory(slot:string):string{
  if(['greet','nod','look'].includes(slot))return '招呼与回应'
  if(['happy','playful','celebrate','sing'].includes(slot))return '愉快与庆祝'
  if(slot==='thinking')return '思考与关注'
  if(['comfort','shy'].includes(slot))return '陪伴与含蓄'
  if(['sad','angry','surprise','surprised'].includes(slot))return '情绪变化'
  if(['idle','neutral'].includes(slot))return '日常待机'
  return '待分类'
}
export function resourceLabel(file:string,slot:string):string{
  const name=file.split('/').at(-1)?.replace(/\.(motion3|exp3)\.json$/,'')||file
  return `${resourceCategory(slot)} · ${name}`
}
