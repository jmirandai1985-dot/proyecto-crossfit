# PENDIENTE DECISION USUARIO

## Cambios de código solicitados:

1. Si el endpoint GET /wods/hoy debe aceptar un parámetro `fecha` opcional
   (para que coach pueda consultar WODs de días futuros), confírmalo y lo
   implementamos. Por ahora no se tocó porque no es un bug — el endpoint
   solo responde "hoy" por diseño.

## Notas
- Los 2 "bugs" reportados inicialmente eran errores del script de prueba,
  no del backend. Las disciplinas Levantamiento Olímpico (id=5) y Clase
  Intensiva Sabado (id=6) ya existen en BD.
- Tests: 28/28 passed en 149.47s.