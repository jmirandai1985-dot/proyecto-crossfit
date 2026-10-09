/**
 * hace — texto de antigüedad relativa ("hace 12 min", "ayer", "hace 18 días").
 *
 * POR QUÉ EXISTE: el panel móvil del admin muestra la antigüedad de varias cosas
 * (solicitud de voucher, correo enviado, pedido esperando retiro). Estaba escrito
 * dentro del componente del dashboard (una sola copia) y ahora lo necesitan también
 * la tarjeta "Alumnos nuevos y en prueba" y la pantalla "Pedidos listos para
 * entrega": vive acá para que las tres digan lo MISMO (y se pueda testear aislado).
 *
 * `ahora` se inyecta (default `Date.now()`) sólo para poder probar el corte de cada
 * tramo sin depender del reloj.
 */

/** "ahora" / "hace 12 min" / "hace 2 h" / "ayer" / "hace 18 días" (o "" sin fecha). */
export const textoHace = (valor, ahora = Date.now()) => {
    if (!valor) return '';
    const d = new Date(valor);
    if (isNaN(d.getTime())) return '';
    const minutos = Math.max(0, Math.round((ahora - d.getTime()) / 60000));
    if (minutos < 1) return 'ahora';
    if (minutos < 60) return `hace ${minutos} min`;
    const horas = Math.round(minutos / 60);
    if (horas < 24) return `hace ${horas} h`;
    const dias = Math.round(horas / 24);
    return dias === 1 ? 'ayer' : `hace ${dias} días`;
};

/** Igual que `textoHace`, con el rótulo adelante: "Enviado hace 5 min", "Enviado ayer". */
export const textoHaceCon = (prefijo, valor, ahora = Date.now()) => {
    const texto = textoHace(valor, ahora);
    return texto ? `${prefijo} ${texto}` : '';
};
