export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string) {
    super(mensaje)
    this.name = 'ErrorApi'
  }
}
