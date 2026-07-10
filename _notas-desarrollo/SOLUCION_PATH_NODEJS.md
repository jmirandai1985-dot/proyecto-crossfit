# Solución: Node.js instalado pero no en el PATH

## Problema Detectado

Node.js está instalado correctamente (versión v24.17.0), pero el sistema no lo encuentra en el PATH. Esto significa que Windows no sabe dónde buscar el comando `node`.

## Solución: Agregar Node.js al PATH del Sistema

### Opción 1: Reiniciar la Computadora (Más Simple)

1. **Guarda todo tu trabajo**
2. **Reinicia tu computadora**
3. Después del reinicio, abre VS Code nuevamente
4. Abre una nueva terminal y prueba: `node -v`

### Opción 2: Agregar Manualmente al PATH (Sin Reiniciar)

1. Presiona `Windows + R` para abrir "Ejecutar"
2. Escribe: `sysdm.cpl` y presiona Enter
3. Ve a la pestaña **"Opciones avanzadas"**
4. Haz clic en **"Variables de entorno"**
5. En la sección **"Variables del sistema"**, busca la variable **"Path"**
6. Selecciónala y haz clic en **"Editar"**
7. Haz clic en **"Nuevo"** y agrega esta ruta:
   ```
   C:\Program Files\nodejs\
   ```
8. Haz clic en **"Aceptar"** en todas las ventanas
9. **Cierra completamente VS Code** (todas las ventanas)
10. Abre VS Code nuevamente
11. Abre una nueva terminal y prueba: `node -v`

### Opción 3: Usar PowerShell para Agregar al PATH (Temporal)

Si necesitas una solución temporal para esta sesión:

1. Abre PowerShell como Administrador
2. Ejecuta:
   ```powershell
   $env:Path += ";C:\Program Files\nodejs\"
   ```
3. Verifica: `node -v`

**NOTA**: Esta solución es temporal y solo funciona para esa sesión de PowerShell.

## Verificación

Una vez aplicada cualquiera de las soluciones, verifica que funcione:

```bash
node -v
npm -v
```

Ambos comandos deberían mostrar las versiones instaladas.

## Siguiente Paso

Una vez que `node -v` funcione sin necesidad de especificar la ruta completa, avísame y continuaremos con la creación del proyecto React con Vite.
