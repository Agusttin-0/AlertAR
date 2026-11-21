#pragma once
// Copiar como conectividad_secrets.h, ignorado por Git.
// No compartir este archivo ni el firmware compilado con credenciales reales.
#define ALERTAR_CONECTIVIDAD_HABILITADA false
// Reemplazar <servidor> por la dirección del servidor de AlertAR (con su puerto, si no es 443).
// La URL de reserva lleva el dispositivo_id del paso (esp32-01, esp32-02, ...).
#define ALERTAR_API_URL "https://<servidor>:8443/api/eventos"
#define ALERTAR_RESERVA_API_URL "https://<servidor>:8443/api/dispositivos/esp32-01/reserva"
#define ALERTAR_DEVICE_KEY ""
