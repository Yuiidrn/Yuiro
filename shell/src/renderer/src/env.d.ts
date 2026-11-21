import type { YuiroBridge } from '../../preload/index'

declare global {
  interface Window {
    yuiro: YuiroBridge
  }
}

export { }
