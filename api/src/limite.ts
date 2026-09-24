/**
 * Limite de tentativas de login (contra adivinhação de senha por força bruta).
 *
 * Conta as falhas por chave (o login tentado e, separado, o IP) numa janela de tempo.
 * Passou do limite, a chave fica bloqueada até a janela vencer. Contar só por IP não
 * basta (o atacante troca de IP) e só por login também não (tenta uma senha comum em
 * muitos logins); por isso as duas contagens.
 *
 * Limitação conhecida: fica na memória de um processo. Com várias instâncias da API
 * atrás de um balanceador, o contador teria de ir para um lugar comum (Redis ou o banco).
 */
export class LimiteDeTentativas {
  private readonly falhas = new Map<string, { quantidade: number; desde: number }>();

  constructor(
    private readonly maximo: number,
    private readonly janelaMs: number,
    private readonly agora: () => number = Date.now,
  ) {}

  /** Segundos até liberar, ou 0 se a chave não está bloqueada. */
  segundosBloqueado(chave: string): number {
    const registro = this.falhas.get(chave);
    if (registro === undefined) return 0;
    const decorrido = this.agora() - registro.desde;
    if (decorrido >= this.janelaMs) {
      this.falhas.delete(chave);
      return 0;
    }
    return registro.quantidade >= this.maximo ? Math.ceil((this.janelaMs - decorrido) / 1000) : 0;
  }

  registrarFalha(chave: string): void {
    const agora = this.agora();
    const registro = this.falhas.get(chave);
    if (registro === undefined || agora - registro.desde >= this.janelaMs) {
      this.falhas.set(chave, { quantidade: 1, desde: agora });
    } else {
      registro.quantidade += 1;
    }
    // Memória limitada: um atacante com milhões de logins inventados não esgota a RAM.
    if (this.falhas.size > 10_000) this.limparVencidos();
  }

  limpar(chave: string): void {
    this.falhas.delete(chave);
  }

  private limparVencidos(): void {
    const agora = this.agora();
    for (const [chave, registro] of this.falhas) {
      if (agora - registro.desde >= this.janelaMs) this.falhas.delete(chave);
    }
  }
}
