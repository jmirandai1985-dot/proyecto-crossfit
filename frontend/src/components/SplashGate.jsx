import { useState } from 'react';
import SplashGorila from './SplashGorila';

const FLAG_KEY = 'splash_gorila_mostrado';

function debeMostrarSplash() {
  try {
    const rol = localStorage.getItem('rol');
    const yaMostrado = sessionStorage.getItem(FLAG_KEY);
    const rolAplica = rol === 'alumno' || !rol;
    return rolAplica && !yaMostrado;
  } catch {
    return false;
  }
}

export default function SplashGate({ children }) {
  const [mostrando, setMostrando] = useState(debeMostrarSplash);

  const terminar = () => {
    try {
      sessionStorage.setItem(FLAG_KEY, '1');
    } catch {
      /* ignorar si sessionStorage no está disponible */
    }
    setMostrando(false);
  };

  if (mostrando) {
    return <SplashGorila onFinish={terminar} />;
  }

  return children;
}
