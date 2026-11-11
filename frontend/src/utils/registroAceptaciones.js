/**
 * registroAceptaciones — regla PURA del alta de alumno (FUENTE ÚNICA).
 *
 * El alta pública exige dos consentimientos INDEPENDIENTES:
 *   - Términos y Condiciones + Política de Tratamiento de Datos Personales;
 *   - Declaración de salud (NO es una cláusula de exención de responsabilidad).
 *
 * Vive acá (sin React ni red) para poder probarse aislado, igual que
 * `utils/fichaAlumno.js` o `utils/alumnos.js`. El submit de
 * `RegistroAlumnoNuevo` se bloquea si falta cualquiera de los dos.
 */
export function validarAceptaciones({ acepta_tyc, acepta_salud }) {
    const errores = {};
    if (!acepta_tyc) errores.acepta_tyc = true;
    if (!acepta_salud) errores.acepta_salud = true;
    return { valido: Object.keys(errores).length === 0, errores };
}
