/** 模型实例内的持续表情；一次性演出不会覆盖它。 */
export class ExpressionBaseline {
  private name = ''

  update(name: string, temporary: boolean): void {
    if (!temporary) this.name = name
  }

  current(): string { return this.name }
  reset(): void { this.name = '' }
}
