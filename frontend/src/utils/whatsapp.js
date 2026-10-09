/**
 * whatsapp — enlace de contacto por WhatsApp (wa.me) para el buscador móvil del admin.
 *
 * POR QUÉ EXISTE: en `usuarios.telefono` los números están cargados a mano, sin formato
 * único: "+56 9 1234 5678", "912345678", "56912345678", "(9) 1234-5678"… wa.me necesita
 * SOLO dígitos con código de país. Y el teléfono puede faltar: en ese caso el botón del
 * panel NO se dibuja (`telefonoWhatsapp` devuelve null), en vez de abrir un chat roto.
 *
 * Reglas (Chile):
 *   · 9 dígitos que empiezan en 9 (celular local)      -> 56 + los 9 dígitos
 *   · 8 dígitos (fijo local, sin área)                 -> 56 + los 8 dígitos
 *   · 11 dígitos que empiezan en 56 (ya viene del país)-> tal cual
 *   · otros largos (10, 12+, internacionales)          -> tal cual (se respeta lo cargado)
 *   · menos de 8 dígitos o sin datos                   -> null (no se puede contactar)
 */

/** Solo dígitos de un valor de teléfono (saca +, espacios, guiones y paréntesis). */
export const soloDigitos = (telefono) => String(telefono ?? '').replace(/\D/g, '');

/** Número listo para wa.me, o null si el teléfono no alcanza para armar el enlace. */
export const telefonoWhatsapp = (telefono) => {
    const digitos = soloDigitos(telefono);
    if (!digitos || digitos.length < 8) return null;
    if (digitos.startsWith('56')) return digitos;
    return `56${digitos}`;
};

/** URL de WhatsApp con mensaje opcional, o null si no hay teléfono usable. */
export const enlaceWhatsapp = (telefono, mensaje = '') => {
    const numero = telefonoWhatsapp(telefono);
    if (!numero) return null;
    const texto = mensaje ? `?text=${encodeURIComponent(mensaje)}` : '';
    return `https://wa.me/${numero}${texto}`;
};
