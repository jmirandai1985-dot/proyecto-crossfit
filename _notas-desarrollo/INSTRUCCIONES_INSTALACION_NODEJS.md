# Instrucciones para Instalar Node.js en Windows

## Paso 1: Descargar Node.js

1. Abre tu navegador web
2. Ve a la página oficial: **https://nodejs.org/**
3. Verás dos versiones disponibles:
   - **LTS (Long Term Support)** - Recomendada para la mayoría de usuarios
   - **Current** - Última versión con las características más recientes

4. **Descarga la versión LTS** (recomendada)

## Paso 2: Instalar Node.js

1. Una vez descargado el archivo `.msi`, haz doble clic para ejecutarlo
2. Sigue el asistente de instalación:
   - Acepta los términos de licencia
   - Deja la ruta de instalación por defecto (C:\Program Files\nodejs\)
   - **IMPORTANTE**: Asegúrate de que la opción "Add to PATH" esté marcada
   - Acepta instalar las herramientas necesarias (npm, etc.)
3. Haz clic en "Install" y espera a que termine
4. Haz clic en "Finish"

## Paso 3: Verificar la Instalación

1. **IMPORTANTE**: Cierra todas las ventanas de terminal/CMD que tengas abiertas
2. Abre una **NUEVA** ventana de CMD o PowerShell
3. Ejecuta los siguientes comandos:

```bash
node -v
```

Deberías ver algo como: `v20.x.x` o similar

```bash
npm -v
```

Deberías ver algo como: `10.x.x` o similar

## Paso 4: Reiniciar VS Code

1. Cierra completamente Visual Studio Code
2. Vuelve a abrirlo
3. Esto asegurará que VS Code reconozca Node.js en el PATH

## ¿Problemas?

Si después de instalar Node.js y reiniciar, el comando `node -v` aún no funciona:

1. Reinicia tu computadora
2. Verifica que Node.js esté en el PATH del sistema:
   - Busca "Variables de entorno" en Windows
   - Verifica que `C:\Program Files\nodejs\` esté en la variable PATH

## Siguiente Paso

Una vez que `node -v` funcione correctamente, avísame y continuaremos con la creación del proyecto React con Vite.
