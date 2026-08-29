# Desplegar en la nube (sin PC encendido)

Tu iPhone se conecta a un servidor en internet que **siempre está activo** y lee Hostalia automáticamente.

## Opción recomendada: Render (gratis)

### 1. Sube el código a GitHub
Crea un repositorio y sube la carpeta `facturas/`.

### 2. Crea cuenta en [render.com](https://render.com)

### 3. Nuevo → Web Service → conecta tu repo
- **Root directory:** `facturas`
- **Runtime:** Docker
- Render detectará el `Dockerfile` automáticamente

### 4. Variables de entorno (Environment)
```
EMAIL_ACCOUNTS=Gerencia@tallerescatala.com:Jeep+2017,taller@tallerescatala.com:Alfa+2017
RECIPIENT_NAME=Talleres Catala Automotive SL
IMAP_SERVER=imap.servidor-correo.net
IMAP_PORT=993
AUTO_SYNC_HOURS=4
CRON_SECRET=elige_una_clave_secreta
```

### 5. Disco persistente (importante)
En Render → tu servicio → **Disks** → añade:
- Mount path: `/app/data`
- 1 GB

(Sin esto se pierden las facturas al reiniciar.)

### 6. Despliega
Obtendrás una URL como: `https://facturas-talleres-catala.onrender.com`

### 7. Instala en el iPhone
1. Abre esa URL en **Safari**
2. Compartir ⬆️ → **Añadir a pantalla de inicio**
3. ¡Listo! Ya no necesitas el PC.

---

## Mantener sincronización (plan gratis Render)

Render free se duerme tras inactividad. Configura [cron-job.org](https://cron-job.org) (gratis):

- URL: `https://TU-URL.onrender.com/api/cron/sync`
- Cada 4 horas
- Header: `X-Cron-Secret` = tu `CRON_SECRET`

Así el servidor se despierta y sincroniza el correo solo.

---

## Resumen

| Antes | Ahora |
|-------|-------|
| PC encendido 24h | Servidor en la nube |
| Solo en casa (WiFi) | Desde cualquier sitio con 4G/5G |
| Sincronizar manual | Cada 4 horas automático |
