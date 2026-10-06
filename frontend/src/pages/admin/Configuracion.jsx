import React, { useCallback, useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { fmtFechaChile, horaChileStr } from '../../utils/fecha';

/**
 * Mensaje legible de un error de la API.
 *
 * Un 422 de FastAPI trae `detail` como LISTA de errores de Pydantic (validaciones de
 * `ConfiguracionUpdate`): hay que armar el texto campo por campo, si no la pantalla
 * muestra "[object Object]" y el admin no sabe qué corregir.
 */
const detalleDeError = (err) => {
    const detalle = err.response?.data?.detail;
    if (typeof detalle === 'string') return detalle;
    if (Array.isArray(detalle)) {
        const lineas = detalle.map((e) => {
            const campo = (e.loc || []).filter((p) => p !== 'body').join('.');
            const msg = String(e.msg || '').replace(/^Value error, /, '');
            return campo ? `${campo}: ${msg}` : msg;
        });
        if (lineas.length) return lineas.join(' · ');
    }
    return 'No se pudo guardar. Revisa los datos e intenta nuevamente.';
};

const Configuracion = () => {
    const { tenant_id } = useAuth();
    const [form, setForm] = useState({
        banco: '',
        numero_cuenta: '',
        tipo_cuenta: '',
        rut: '',
        email_comprobantes: '',
        whatsapp: '',
    });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState({ type: '', text: '' });
    // I4/I5: el resultado de la carga se GUARDA en el estado (antes sólo iba a
    // `console.error`). Esta pantalla ESCRIBE datos bancarios, así que el admin tiene que
    // ver que no se pudo leer lo guardado —y no poder guardar encima a ciegas.
    const [configurado, setConfigurado] = useState(false);
    const [errorCarga, setErrorCarga] = useState('');
    const [updatedAt, setUpdatedAt] = useState(null);

    // `useCallback` porque la usan el efecto Y el botón "Reintentar" del aviso de error:
    // así la dependencia del efecto es la función y no hay warning de exhaustive-deps.
    const fetchConfig = useCallback(async () => {
        setErrorCarga('');
        try {
            const res = await api.get(`/api/v1/configuracion?tenant_id=${tenant_id}`);
            const data = res.data;
            setConfigurado(!!data.configurado);
            setUpdatedAt(data.updated_at || null);
            if (data.configurado) {
                setForm({
                    banco: data.banco || '',
                    numero_cuenta: data.numero_cuenta || '',
                    tipo_cuenta: data.tipo_cuenta || '',
                    rut: data.rut || '',
                    email_comprobantes: data.email_comprobantes || '',
                    whatsapp: data.whatsapp || '',
                });
            }
        } catch (err) {
            console.error('Error cargando config:', err);
            setErrorCarga('No se pudieron cargar los datos bancarios guardados. Si guardas ahora, puedes sobrescribir sin ver lo que hay.');
        }
    }, [tenant_id]);

    useEffect(() => {
        setLoading(true);
        fetchConfig().finally(() => setLoading(false));
    }, [fetchConfig]);

    const handleChange = (e) => {
        setForm({ ...form, [e.target.name]: e.target.value });
    };

    const handleSave = async (e) => {
        e?.preventDefault();
        // M6: guardar con datos ya cargados los REEMPLAZA (y el otro admin del box no ve
        // este formulario): se pide confirmación explícita antes de pisar.
        if (configurado && !window.confirm(
            'Ya hay datos bancarios guardados y se van a reemplazar por los de este formulario. ¿Guardar?')) {
            return;
        }
        setSaving(true);
        setMessage({ type: '', text: '' });
        try {
            const res = await api.put(`/api/v1/configuracion`, form);
            setConfigurado(true);
            setUpdatedAt(res.data?.updated_at || null);
            setMessage({ type: 'success', text: 'Datos bancarios guardados exitosamente.' });
        } catch (err) {
            setMessage({ type: 'error', text: detalleDeError(err) });
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500"></div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-2xl mx-auto space-y-6">
                <div className="flex items-center gap-3">
                    <span className="text-3xl">⚙️</span>
                    <div>
                        <h1 className="text-2xl font-bold text-zinc-100">Configuración</h1>
                        <p className="text-sm text-zinc-400">Datos bancarios para transferencias de los alumnos</p>
                    </div>
                </div>

                {message.text && (
                    <div className={`p-4 rounded-xl border text-sm font-medium ${message.type === 'success'
                            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                            : 'bg-red-50 border-red-200 text-red-700'
                        }`}>
                        {message.type === 'success' ? '✅' : '❌'} {message.text}
                    </div>
                )}

                {/* I5: si la carga falló, se dice y se deshabilita Guardar (estos datos
                    bancarios los lee el alumno para transferir: guardar a ciegas encima de
                    lo que hay es peor que no guardar). */}
                {errorCarga && (
                    <div role="alert" data-testid="config-error-carga"
                        className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-200">
                        <span>⚠️ {errorCarga}</span>
                        <button type="button" onClick={fetchConfig}
                            data-testid="config-reintentar"
                            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 transition-colors">
                            Reintentar
                        </button>
                    </div>
                )}

                {/* I4: el box no tiene fila guardada. Antes la pantalla se veía igual que con
                    datos cargados (formulario vacío) y el admin no sabía si faltaba cargarlos. */}
                {!configurado && !errorCarga && (
                    <div data-testid="config-sin-datos"
                        className="rounded-xl border border-amber-700 bg-amber-900/30 px-4 py-3 text-sm text-amber-200">
                        📭 <strong>Todavía no has cargado los datos bancarios.</strong> Mientras no los
                        cargues, los alumnos no pueden transferir: el Bazar bloquea los pedidos y en
                        Solicitar plan sólo ven "el box aún no ha configurado sus datos de pago".
                    </div>
                )}

                {configurado && updatedAt && (
                    <p className="text-xs text-zinc-500" data-testid="config-ultima-modificacion">
                        Última modificación: {fmtFechaChile(updatedAt)} {horaChileStr(updatedAt)}
                        {/* El "quién" (updated_by) lo avisa la campana del panel: los admins del
                            box se enteran cuando el otro cambia estos datos. */}
                    </p>
                )}

                <form onSubmit={handleSave} className="bg-zinc-900 rounded-xl border border-zinc-800 p-6 shadow-sm space-y-5">
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Banco</label>
                        <input type="text" name="banco" value={form.banco} onChange={handleChange}
                            placeholder="Ej: Banco Santander" maxLength={200}
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Número de Cuenta</label>
                        <input type="text" name="numero_cuenta" value={form.numero_cuenta} onChange={handleChange}
                            placeholder="Ej: 12345678" maxLength={50}
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                        <p className="text-xs text-zinc-500 mt-1">
                            Sólo dígitos (se aceptan puntos y guiones: se guardan sin ellos).
                        </p>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Tipo de Cuenta</label>
                        <select name="tipo_cuenta" value={form.tipo_cuenta} onChange={handleChange}
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm">
                            <option value="">Seleccionar...</option>
                            <option value="Corriente">Corriente</option>
                            <option value="Vista">Vista</option>
                            <option value="Rut">RUT</option>
                            <option value="Ahorro">Ahorro</option>
                        </select>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">RUT</label>
                        <input type="text" name="rut" value={form.rut} onChange={handleChange}
                            placeholder="Ej: 12345678-5" maxLength={20}
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                        <p className="text-xs text-zinc-500 mt-1">
                            RUT del titular de la cuenta. Se valida el dígito verificador.
                        </p>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">Email para Comprobantes</label>
                        <input type="email" name="email_comprobantes" value={form.email_comprobantes} onChange={handleChange}
                            placeholder="Ej: pagos@urbanbox.cl" maxLength={200}
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-zinc-300 mb-1">WhatsApp / Teléfono del box</label>
                        <input type="text" name="whatsapp" value={form.whatsapp} onChange={handleChange}
                            placeholder="Ej: +56 9 1234 5678"
                            maxLength={30}
                            data-testid="config-whatsapp"
                            className="w-full px-4 py-2.5 border border-zinc-700 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 text-sm" />
                        <p className="text-xs text-zinc-500 mt-1">
                            Va en el pie de todos los correos a los alumnos: "responde este correo o escríbenos al WhatsApp".
                            Si lo dejas vacío, los correos sólo ofrecen responder el correo.
                        </p>
                    </div>

                    <button type="submit" disabled={saving || !!errorCarga}
                        data-testid="config-guardar"
                        className="w-full py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50">
                        {saving ? 'Guardando...' : '💾 Guardar'}
                    </button>
                </form>
            </div>
        </Layout>
    );
};

export default Configuracion;