import React from 'react';

/**
 * Toast — aviso flotante de resultado (Bloque 2: confirmación antes de descontar).
 *
 * POR QUÉ EXISTE: el walk-in del coach ("+ Agregar alumno sin reserva") descuenta un
 * crédito, y el resultado tiene que verse aunque el modal ya se haya cerrado. El modal
 * se desmonta al cerrarse, así que el aviso NO puede vivir adentro: lo pinta la pantalla
 * que lo abrió (que sigue montada) con el texto que le pasa el modal en `onAgregado`
 * (`alumno.mensaje`), para que el texto se escriba UNA sola vez (en el modal, pegado a la
 * rama que realmente ejecuta).
 *
 * Es PRESENTACIONAL a propósito: sin estado ni temporizador. Quien lo usa decide cuándo
 * se va (mismo patrón que el `avisar()` del Inicio móvil del admin: `setToast(texto)` +
 * `setTimeout(() => setToast(null), 2600)`), así que no hay dos relojes distintos.
 *
 * `role="status"` para que un lector de pantalla lo anuncie sin robar el foco, y
 * `z-[80]` para quedar por encima de los modales (`z-50`/`z-60`).
 */
const Toast = ({ texto, tono = 'exito' }) => {
    if (!texto) return null;
    const paleta = tono === 'error'
        ? 'border-red-700 bg-red-950/95 text-red-100'
        : 'border-emerald-700 bg-emerald-950/95 text-emerald-100';
    return (
        <div
            role="status"
            data-testid="toast"
            className={`fixed inset-x-4 bottom-4 z-[80] mx-auto w-fit max-w-[92vw] rounded-xl border px-4 py-3 text-center text-[13px] font-semibold shadow-2xl ${paleta}`}
        >
            {texto}
        </div>
    );
};

export default Toast;
