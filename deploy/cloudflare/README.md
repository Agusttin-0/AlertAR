# Panel público en Cloudflare Pages

Publica el panel en **https://alertar.pages.dev** sin abrir puertos ni pagar hosting. Cloudflare Pages hace de puerta de entrada y el servidor de AlertAR sigue corriendo donde está (expuesto con Tailscale Funnel, ver [docs/despliegue.md](../../docs/despliegue.md)).

## Cómo funciona

`public/_worker.js` recibe todos los pedidos a `alertar.pages.dev`:

- **Archivos fijos y página pública:** el CSS, el JavaScript, el logo y la página `/` sin sesión se sirven desde Cloudflare. El servidor no los manda a cada visitante.
- **Datos en vivo:** las lecturas públicas (`/api/panel`, `/api/tuneles`, estado, historial) se guardan 2 s en memoria y se comparten entre todos los visitantes; las estadísticas, 20 s. Si el servidor tarda, se entrega la última respuesta (hasta 15 s, o 2 min para estadísticas) y se actualiza en segundo plano.
- **Administración:** con la sesión iniciada (cookie), todo va directo al servidor, sin caché.
- Las redirecciones del servidor (login, salir) se reescriben para que el navegador siga en `alertar.pages.dev`.

Así una clase entera puede tener el panel abierto aunque el servidor esté en una conexión hogareña.

## Servidor de destino

El destino está fijo en `ORIGEN`, al principio de `public/_worker.js`: el servidor Lenovo (`lenovo-server.tail197fd6.ts.net:8443`), que reemplazó al Dell después de la exposición. No hay cambio automático a otro servidor. Si el principal se cae:

1. Cambiar `ORIGEN` por la URL de Funnel del servidor de reserva y volver a publicar.
2. Para que el panel muestre datos en vivo, el ESP32 (o Wokwi) también tiene que enviar a ese servidor: cambiar `ALERTAR_API_URL` y `ALERTAR_RESERVA_API_URL` en `AlertAR-2/include/conectividad_secrets.h` y volver a compilar. Cada servidor tiene su propia base de datos.

## Publicar

Desde la raíz del repositorio, con Node instalado:

```bash
npx wrangler login
sh deploy/cloudflare/publicar.sh
```

El script copia `backend/static/`, genera `public/index.html` con Flask y publica. Hay que volver a correrlo después de cambiar el panel (`backend/static/` o `backend/templates/panel.html`); si no, la página pública queda desactualizada respecto del servidor. El proyecto de Pages `alertar` pertenece a una cuenta de Cloudflare: para publicar hay que tener acceso a esa cuenta.
