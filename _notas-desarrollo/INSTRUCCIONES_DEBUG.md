# INSTRUCCIONES PARA DIAGNOSTICAR EL ERROR DE CONTRASEÑA

## Código Actual Implementado

### 1. Función hash_password en backend/app/api/v1/usuarios.py (líneas 19-32)

```python
def hash_password(password: str) -> str:
    """Hashea una contraseña usando bcrypt (máximo 72 bytes)"""
    # DEBUG: Imprimir longitud de la contraseña recibida
    print(
        f"[DEBUG] Longitud de contraseña recibida: {len(password)} caracteres")
    print(f"[DEBUG] Contraseña recibida (primeros 50 chars): {password[:50]}")
    print(f"[DEBUG] Tipo de dato: {type(password)}")

    # Bcrypt tiene un límite de 72 bytes, truncar si es necesario
    password_truncated = password[:72]
    print(
        f"[DEBUG] Longitud después de truncar: {len(password_truncated)} caracteres")
    return pwd_context.hash(password_truncated)
```

### 2. Función crear_usuario en backend/app/api/v1/usuarios.py (líneas 38-100)

```python
@router.post("/", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    usuario_data: UsuarioCreate,
    db: Session = Depends(get_db)
):
    """
    Crea un nuevo usuario en el sistema

    - **tenant_id**: ID del box al que pertenece
    - **rut**: RUT único dentro del tenant
    - **nombre**: Nombre completo
    - **correo**: Email único dentro del tenant
    - **password**: Contraseña (será hasheada)
    - **rol**: alumno, coach o administrador
    """
    # Verificar si el RUT ya existe en este tenant
    existing_rut = db.query(Usuario).filter(
        Usuario.tenant_id == usuario_data.tenant_id,
        Usuario.rut == usuario_data.rut
    ).first()

    if existing_rut:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario con el RUT {usuario_data.rut} en este box"
        )

    # Verificar si el correo ya existe en este tenant
    existing_email = db.query(Usuario).filter(
        Usuario.tenant_id == usuario_data.tenant_id,
        Usuario.correo == usuario_data.correo
    ).first()

    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un usuario con el correo {usuario_data.correo} en este box"
        )

    # Crear el nuevo usuario
    db_usuario = Usuario(
        tenant_id=usuario_data.tenant_id,
        rut=usuario_data.rut,
        nombre=usuario_data.nombre,
        telefono=usuario_data.telefono,
        correo=usuario_data.correo,
        password_hash=hash_password(usuario_data.password),  # <-- AQUÍ SE LLAMA hash_password
        rol=usuario_data.rol,
        activo=True
    )

    db.add(db_usuario)
    db.commit()
    db.refresh(db_usuario)

    return db_usuario
```

### 3. Schema UsuarioCreate en backend/app/schemas/usuario.py (líneas 26-31)

```python
class UsuarioCreate(UsuarioBase):
    """Schema para crear un nuevo usuario"""
    tenant_id: int = Field(..., gt=0,
                           description="ID del tenant (box) al que pertenece")
    password: str = Field(..., min_length=6, max_length=100,
                          description="Contraseña del usuario")
```

## Pasos para Reproducir el Error y Ver el Debug

1. **Asegúrate de que el backend está corriendo** con los cambios guardados
2. **Abre la consola del servidor backend** para ver los prints de DEBUG
3. **En el frontend, intenta crear un usuario administrador** con contraseña "Test1234"
4. **Mira la consola del backend** y copia aquí los mensajes [DEBUG] que aparezcan

## Qué Esperamos Ver

Si todo funciona correctamente, deberías ver algo como:

```
[DEBUG] Longitud de contraseña recibida: 8 caracteres
[DEBUG] Contraseña recibida (primeros 50 chars): Test1234
[DEBUG] Tipo de dato: <class 'str'>
[DEBUG] Longitud después de truncar: 8 caracteres
```

Si ves una longitud mayor a 72, eso significa que algo está concatenando datos a la contraseña.

## Próximos Pasos

Una vez que veas el output del debug, sabremos exactamente qué está pasando y podremos arreglarlo.
