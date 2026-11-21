/** 配置保留规范 web 路径，SDK加载时才解析相对于当前页面的资源地址。 */
export function modelAssetUrl(path: string, page: string): string {
  const base = new URL(page)
  if (base.protocol === 'file:' && path.startsWith('/live2d/')) {
    return new URL(`.${path}`, base).href
  }
  return path
}
