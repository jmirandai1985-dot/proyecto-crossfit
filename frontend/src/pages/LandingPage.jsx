import React, { useState } from 'react';
import axios from 'axios';

export default function LandingPage() {
  const [formData, setFormData] = useState({
    nombre: '',
    rut: '',
    correo: '',
    genero: '',
    peso_kg: '',
    estatura_cm: ''
  });
  const [mensaje, setMensaje] = useState('');

  const validarRUT = (rut) => /^\d{7,8}-[\dkK]$/.test(rut);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!validarRUT(formData.rut)) {
      setMensaje('❌ RUT inválido (ej: 12345678-9)');
      return;
    }

    try {
      const res = await axios.post('/api/v1/alumnos/registro/alumno-nuevo', {
        nombre: formData.nombre,
        correo: formData.correo,
        rut: formData.rut,
        sexo: formData.genero,
        peso_kg: parseFloat(formData.peso_kg),
        estatura_cm: parseInt(formData.estatura_cm)
      });

      setMensaje('✅ ¡Solicitud recibida! Revisa tu correo (incluyendo SPAM).');
      setFormData({ nombre: '', rut: '', correo: '', genero: '', peso_kg: '', estatura_cm: '' });
    } catch (error) {
      setMensaje('❌ Error: ' + (error.response?.data?.detail || 'Intenta de nuevo'));
    }
  };

  return (
    <div style={{ background: '#0a0e27', color: 'white', minHeight: '100vh', fontFamily: 'Inter, sans-serif', padding: '60px 20px' }}>
      
      <section style={{ textAlign: 'center', marginBottom: '60px' }}>
        <h1 style={{ fontSize: '48px', fontWeight: 'bold', marginBottom: '20px' }}>
          ¡Bienvenido a Urban Training Box!
        </h1>
        <p style={{ fontSize: '20px', color: '#ccc' }}>
          Transforma tu cuerpo. Supera tus límites.
        </p>
        <p style={{ fontSize: '18px', color: '#ff8c00', fontWeight: 'bold' }}>
          ¡Felicidades! Acabas de tomar la mejor decisión para tu salud y rendimiento.
        </p>
      </section>

      <form onSubmit={handleSubmit} style={{ maxWidth: '500px', margin: '0 auto', background: '#1a1f3a', padding: '40px', borderRadius: '8px', border: '2px solid #ff8c00' }}>
        
        <input type="text" placeholder="Nombre completo" value={formData.nombre}
          onChange={(e) => setFormData({...formData, nombre: e.target.value})}
          style={{ width: '100%', padding: '12px', marginBottom: '15px', border: '1px solid #ff8c00', borderRadius: '4px', background: '#0a0e27', color: 'white' }} required />
        
        <input type="text" placeholder="RUT (ej: 12345678-5)" value={formData.rut}
          onChange={(e) => setFormData({...formData, rut: e.target.value})}
          style={{ width: '100%', padding: '12px', marginBottom: '15px', border: '1px solid #ff8c00', borderRadius: '4px', background: '#0a0e27', color: 'white' }} required />
        
        <input type="email" placeholder="Correo electrónico" value={formData.correo}
          onChange={(e) => setFormData({...formData, correo: e.target.value})}
          style={{ width: '100%', padding: '12px', marginBottom: '15px', border: '1px solid #ff8c00', borderRadius: '4px', background: '#0a0e27', color: 'white' }} required />
        
        <select value={formData.genero} onChange={(e) => setFormData({...formData, genero: e.target.value})}
          style={{ width: '100%', padding: '12px', marginBottom: '15px', border: '1px solid #ff8c00', borderRadius: '4px', background: '#0a0e27', color: 'white' }} required>
          <option value="">Sexo</option>
          <option value="M">Masculino</option>
          <option value="F">Femenino</option>
        </select>
        
        <input type="number" placeholder="Peso (kg)" value={formData.peso_kg}
          onChange={(e) => setFormData({...formData, peso_kg: e.target.value})}
          style={{ width: '100%', padding: '12px', marginBottom: '15px', border: '1px solid #ff8c00', borderRadius: '4px', background: '#0a0e27', color: 'white' }} required />
        
        <input type="number" placeholder="Estatura (cm)" value={formData.estatura_cm}
          onChange={(e) => setFormData({...formData, estatura_cm: e.target.value})}
          style={{ width: '100%', padding: '12px', marginBottom: '15px', border: '1px solid #ff8c00', borderRadius: '4px', background: '#0a0e27', color: 'white' }} required />
        
        <button type="submit" style={{ width: '100%', padding: '14px', background: '#ff8c00', color: '#0a0e27', fontWeight: 'bold', fontSize: '16px', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
          ¡QUIERO MI CLASE DE PRUEBA AHORA!
        </button>
      </form>

      {mensaje && (
        <div style={{ maxWidth: '500px', margin: '20px auto', padding: '15px', background: '#1a1f3a', borderRadius: '4px', border: '1px solid #ff8c00', textAlign: 'center' }}>
          {mensaje}
        </div>
      )}

    </div>
  );
}
