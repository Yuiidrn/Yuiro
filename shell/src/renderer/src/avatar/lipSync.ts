/** Cubism4口型在动作/表情/物理之后、顶点更新之前写入。 */
export function applyLipSync(core: {setParameterValueById:(id:string,value:number)=>void}, ids: string[], value: number): void {
  const level = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0
  for (const id of ids) core.setParameterValueById(id, level)
}
