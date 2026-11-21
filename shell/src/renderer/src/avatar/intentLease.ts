/** 适配器的短期动作占用；低优先级不能截断已开始的表演。 */
export class IntentLease {
  private priority = -1
  private until = 0
  accepts(priority: number, now: number): boolean {
    return now >= this.until || priority >= this.priority
  }
  hold(priority: number, until: number): void {
    this.priority = priority
    this.until = until
  }
  reset(): void { this.priority = -1; this.until = 0 }
}
