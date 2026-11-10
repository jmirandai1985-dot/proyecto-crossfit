import { useEffect, useRef, useState } from 'react';
import frame0 from '../assets/splash/frame0-intacto.jpg';
import frame1 from '../assets/splash/frame1-grietas.jpg';
import frame2 from '../assets/splash/frame2-brazos.jpg';
import frame3 from '../assets/splash/frame3-quiebre.jpg';
import frame4 from '../assets/splash/frame4-final.jpg';
import '../styles/splashGorila.css';

const FRAMES = [frame0, frame1, frame2, frame3, frame4];
const DURACION_FRAME_MS = 550;
const HOLD_FINAL_MS = 1100;
const FADE_MS = 400;

export default function SplashGorila({ onFinish }) {
  const [frameActual, setFrameActual] = useState(0);
  const [shake, setShake] = useState(false);
  const [mostrarTexto, setMostrarTexto] = useState(false);
  const [fadeOut, setFadeOut] = useState(false);

  const onFinishRef = useRef(onFinish);
  onFinishRef.current = onFinish;

  useEffect(() => {
    const timers = [];
    FRAMES.forEach((_, i) => {
      if (i === 0) return;
      timers.push(
        setTimeout(() => {
          setFrameActual(i);
          setShake(true);
          setTimeout(() => setShake(false), 200);
          if (i === FRAMES.length - 1) setMostrarTexto(true);
        }, i * DURACION_FRAME_MS)
      );
    });

    const tiempoUltimoFrame = (FRAMES.length - 1) * DURACION_FRAME_MS;
    timers.push(
      setTimeout(() => setFadeOut(true), tiempoUltimoFrame + HOLD_FINAL_MS)
    );
    timers.push(
      setTimeout(() => onFinishRef.current(), tiempoUltimoFrame + HOLD_FINAL_MS + FADE_MS)
    );

    return () => timers.forEach(clearTimeout);
  }, []); // se programa una sola vez al montar, no depende de onFinish

  return (
    <div className={`splash-gorila ${fadeOut ? 'splash-gorila--fade' : ''}`}>
      <img
        src={FRAMES[frameActual]}
        alt=""
        className={`splash-gorila__img ${shake ? 'splash-gorila__img--shake' : ''}`}
      />
      {mostrarTexto && (
        <span className="splash-gorila__texto">URBAN TRAINING BOX</span>
      )}
      {frameActual === FRAMES.length - 1 && (
        <div className="splash-gorila__flash" />
      )}
    </div>
  );
}
