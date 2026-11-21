import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/** 悬停停顿这么久才唤出菜单，防止鼠标路过模型时误触发。 */
const HOVER_DWELL_MS = 140
/** 鼠标离开"模型∪选项列"后的宽容期（给最后微调留缓冲）。 */
const CLOSE_GRACE_MS = 260
/** 模型包围盒向外扩的触发边距，让"靠近模型"也能唤出。 */
const RECT_PAD = 2
/** 选项列（功能泡）命中容差：相邻泡之间的缝隙也算"在列上"，避免手抖滑出即关。 */
const MENU_PAD = 6
/** 鼠标静止超过此间隔无坐标变化视为已离开窗口。 */
const STALE_MS = 600

interface Rect {
  left: number
  top: number
  width: number
  height: number
}

/**
 * 括号功能岛的唤出/收回状态机。
 *
 * 关键：监听挂在 window 上 + capture 阶段。因为 .shell-root 有
 * -webkit-app-region: drag，drag 区会吞掉 target 阶段的 mousemove，
 * 文档级 target 监听器收不到模型区域上的移动事件。capture 阶段在
 * 事件派发前截获，可绕过 drag 吞噬。
 */
export function useBracketMenu(options: {
  getModelRect: () => Rect | null
  getFallbackRect: () => Rect
  hitContour?: (x:number,y:number)=>boolean
  /** 悬停渐隐（免打扰）开启期间禁止呼出功能泡，避免穿透态下误触发。 */
  fadeEnabled?: Ref<boolean>
}) {
  const menuOpen = ref(false)
  let dwellTimer: number | null = null
  let closeTimer: number | null = null
  let lastMoveTs = 0
  /** 最后一次 mousemove 是否已判定为"离开模型∪选项列"。stale 兜底据此决定是否强关。 */
  let lastOutsideAlive = false

  /** 免打扰：渐隐开启时功能泡不可呼出（但仍允许在已展开时正常收回）。 */
  const fadeBlocking = (): boolean => !!options.fadeEnabled?.value

  function clearDwell(): void {
    if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null }
  }

  function clearClose(): void {
    if (closeTimer !== null) { clearTimeout(closeTimer); closeTimer = null }
  }

  function open(): void {
    clearDwell()
    clearClose()
    if (menuOpen.value) return
    // console.debug('[bracket] open')
    menuOpen.value = true
  }

  function closeMenu(): void {
    clearDwell()
    clearClose()
    if (!menuOpen.value) return
    // console.debug('[bracket] close')
    menuOpen.value = false
  }

  function overModel(x: number, y: number): boolean {
    if (options.hitContour) return options.hitContour(x,y)
    const r = options.getModelRect() ?? options.getFallbackRect()
    return (
      x >= r.left - RECT_PAD
      && x <= r.left + r.width + RECT_PAD
      && y >= r.top - RECT_PAD
      && y <= r.top + r.height + RECT_PAD
    )
  }

  /** 鼠标是否落在任一功能泡（选项列）上，含 MENU_PAD 缝隙容差。 */
  function overMenu(x: number, y: number): boolean {
    const els = document.querySelectorAll<HTMLElement>('.bm-icon')
    for (const el of els) {
      const r = el.getBoundingClientRect()
      if (
        x >= r.left - MENU_PAD
        && x <= r.right + MENU_PAD
        && y >= r.top - MENU_PAD
        && y <= r.bottom + MENU_PAD
      ) return true
    }
    return false
  }

  /** 停留在"模型∪选项列"任一区域即保持展开。 */
  function keepAlive(x: number, y: number): boolean {
    return overModel(x, y) || overMenu(x, y)
  }

  function onMouseMove(e: MouseEvent): void {
    lastMoveTs = Date.now()
    const x = e.clientX
    const y = e.clientY
    if (menuOpen.value) {
      // 菜单已展开：在模型或选项列上就保持，都不在则进入宽限期收回
      const alive = keepAlive(x, y)
      lastOutsideAlive = !alive
      if (alive) {
        clearClose()
      } else {
        clearClose()
        closeTimer = window.setTimeout(closeMenu, CLOSE_GRACE_MS)
        // console.debug('[bracket] left model+menu, grace start')
      }
      return
    }
    if (overModel(x, y)) {
      // 免打扰：渐隐开启期间不呼出功能泡
      if (!fadeBlocking() && dwellTimer === null) {
        // console.debug('[bracket] enter model zone, dwell start')
        dwellTimer = window.setTimeout(() => { if (!fadeBlocking()) open(); else clearDwell() }, HOVER_DWELL_MS)
      }
    } else {
      clearDwell()
    }
  }

  function onDocLeave(): void {
    clearDwell()
    if (!menuOpen.value) return
    // 离开文档：若当前指针其实在选项列上（hover 态）则保持，否则宽限期收回
    clearClose()
    closeTimer = window.setTimeout(closeMenu, CLOSE_GRACE_MS)
  }

  function onClick(e: MouseEvent): void {
    if (!menuOpen.value) return
    const t = e.target as HTMLElement | null
    if (t?.closest?.('.bm-icon')) return
    closeMenu()
  }

  // 鼠标静止（不再有 mousemove）超过 STALE_MS：仅当最后一次移动已知"已离开
  // 模型∪选项列"时才强关，避免停在功能泡上不动被误收（透明窗口 mouseleave 不可靠，用 stale 兜底）
  const staleTimer = window.setInterval(() => {
    if (!menuOpen.value) return
    if (lastOutsideAlive && Date.now() - lastMoveTs > STALE_MS) closeMenu()
  }, 200)

  onMounted(() => {
    // capture 阶段：drag 区域（-webkit-app-region: drag）会吞掉 target 阶段
    // 的 mousemove，capture 在派发前截获，可绕过
    window.addEventListener('mousemove', onMouseMove, { capture: true, passive: true } as AddEventListenerOptions)
    document.addEventListener('mouseleave', onDocLeave)
    document.addEventListener('click', onClick)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('mousemove', onMouseMove, { capture: true } as EventListenerOptions)
    document.removeEventListener('mouseleave', onDocLeave)
    document.removeEventListener('click', onClick)
    window.clearInterval(staleTimer)
    clearDwell()
    clearClose()
  })

  return { menuOpen, closeMenu, openMenu: open }
}
