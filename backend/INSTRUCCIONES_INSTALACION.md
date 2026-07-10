# 📦 Instrucciones de Instalación - Backend Box CrossFit

Sigue estos pasos **en orden** para configurar el entorno de desarrollo local.

---

## ✅ Paso 1: Verificar Python instalado

Abre una terminal (CMD o PowerShell) y ejecuta:

```bash
python --version
```

**Debes tener Python 3.10 o superior.** Si no lo tienes, descárgalo desde [python.org](https://www.python.org/downloads/).

---

## ✅ Paso 2: Navegar a la carpeta del backend

```bash
cd C:\Users\Asus\Desktop\proyecto_box_crossfit\backend
```

---

## ✅ Paso 3: Crear entorno virtual

```bash
python -m venv venv
```

Esto creará una carpeta `venv` dentro de `backend` con un entorno Python aislado.

---

## ✅ Paso 4: Activar el entorno virtual

**En Windows (CMD):**
```bash
venv\Scripts\activate
```

**En Windows (PowerShell):**
```bash
venv\Scripts\Activate.ps1
```

**Nota:** Si PowerShell te da un error de permisos, ejecuta esto primero:
```bash
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Cuando el entorno esté activado, verás `(venv)` al inicio de la línea de comandos.

---

## ✅ Paso 5: Instalar dependencias

Con el entorno virtual activado, ejecuta:

```bash
pip install -r requirements.txt
```

Esto instalará FastAPI, SQLAlchemy, Alembic, y todas las librerías necesarias.

**Tiempo estimado:** 2-3 minutos dependiendo de tu conexión.

---

## ✅ Paso 6: Verificar instalación

Ejecuta este comando para verificar que FastAPI se instaló correctamente:

```bash
python -c "import fastapi; print(f'FastAPI {fastapi.__version__} instalado correctamente')"
```

Deberías ver algo como: `FastAPI 0.109.0 instalado correctamente`

---

## ✅ Paso 7: Crear archivo .env (IMPORTANTE)

**NO ejecutes el servidor todavía.** Primero necesitas configurar las variables de entorno.

1. Copia el archivo de ejemplo:
   ```bash
   copy .env.example .env
   ```

2. Abre el archivo `.env` con un editor de texto (Notepad, VS Code, etc.)

3. **Por ahora, déjalo con los valores por defecto.** Cuando tengas la base de datos en Neon, volveremos a este archivo para actualizar `DATABASE_URL`.

---

## ✅ Paso 8: Probar el servidor (sin base de datos)

Ejecuta el servidor de desarrollo:

```bash
uvicorn app.main:app --reload
```

Deberías ver algo como:

```
🚀 Iniciando Box CrossFit Platform API...
📚 Documentación disponible en: http://localhost:8000/docs
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

---

## ✅ Paso 9: Verificar que funciona

Abre tu navegador y ve a:

- **API funcionando:** http://localhost:8000
- **Documentación interactiva (Swagger):** http://localhost:8000/docs

Deberías ver un JSON con:
```json
{
  "message": "Box CrossFit Platform API",
  "status": "online",
  "version": "1.0.0"
}
```

---

## ✅ Paso 10: Detener el servidor

Presiona `CTRL + C` en la terminal para detener el servidor.

---

## 🎉 ¡Listo!

El entorno local está configurado correctamente. Los próximos pasos serán:

1. **Crear la base de datos en Neon** (te guiaré paso a paso cuando estés listo)
2. **Actualizar el archivo `.env`** con la cadena de conexión de Neon
3. **Crear los modelos SQLAlchemy** basados en el schema.sql
4. **Configurar Alembic** para las migraciones
5. **Desarrollar los endpoints** de la API

---

## 🔧 Comandos útiles

### Activar entorno virtual
```bash
venv\Scripts\activate
```

### Desactivar entorno virtual
```bash
deactivate
```

### Ejecutar servidor de desarrollo
```bash
uvicorn app.main:app --reload
```

### Instalar una nueva dependencia
```bash
pip install nombre-paquete
pip freeze > requirements.txt  # Actualizar requirements.txt
```

### Ver dependencias instaladas
```bash
pip list
```

---

## ❓ Problemas comunes

### Error: "python no se reconoce como comando"
- Python no está en el PATH. Reinstala Python y marca la opción "Add Python to PATH".

### Error: "No module named 'fastapi'"
- El entorno virtual no está activado. Ejecuta `venv\Scripts\activate` primero.

### Error de permisos en PowerShell
- Ejecuta: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### El servidor no inicia
- Verifica que estés en la carpeta `backend` (no en `backend/app`)
- Verifica que el entorno virtual esté activado (debes ver `(venv)` en la terminal)

---

## 📞 Siguiente paso

Cuando estés listo para conectar la base de datos, avísame y te guiaré para:
1. Crear la cuenta en Neon
2. Crear la base de datos PostgreSQL
3. Obtener la cadena de conexión
4. Actualizar el archivo `.env`
