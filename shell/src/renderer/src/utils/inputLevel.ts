/** 真实PCM输入的RMS显示电平，4倍显示增益；静音和无效样本不产生假活动。 */
export function inputLevel(samples:Float32Array):number{
  if(!samples.length)return 0
  let sum=0
  for(const value of samples)if(Number.isFinite(value))sum+=value*value
  return Math.min(1,Math.sqrt(sum/samples.length)*4)
}
