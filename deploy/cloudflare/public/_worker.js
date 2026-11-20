// Proxy de alertar.pages.dev hacia el servidor de AlertAR.
//
// Un servidor hogareño tiene poca subida y Funnel suma demora, así que:
//  - Los archivos fijos (CSS, JS, logo) y la página pública "/" se sirven desde Cloudflare
//    (carpeta public/ de este proyecto). El servidor no los envía nunca a los visitantes.
//  - Las lecturas de datos de visitantes sin sesión se guardan unos segundos en memoria: toda
//    la clase comparte la misma respuesta. Si el servidor tarda, se entrega la última respuesta
//    (hasta el tiempo "viejo" de cada regla) y se actualiza en segundo plano.
//  - Con sesión de administrador (cookie) todo va directo al servidor.

// Servidor principal (Tailscale Funnel). Si se cae, se cambia a mano por otro y se vuelve a publicar.
const ORIGEN = "https://lenovo-server.tail197fd6.ts.net:8443";
// fresco: se entrega sin consultar; viejo: se entrega mientras se actualiza en segundo plano.
const LECTURAS = [
  { re: /^\/api\/panel\/[^/]+$/, fresco: 2000, viejo: 15000 },        // estado en vivo
  { re: /^\/api\/tuneles$/, fresco: 2000, viejo: 15000 },
  { re: /^\/api\/pasos\/[^/]+\/(estado|historial)$/, fresco: 2000, viejo: 15000 },
  { re: /^\/api\/pasos\/[^/]+\/estadisticas$/, fresco: 20000, viejo: 120000 }, // gráficos (25-30 KB)
];
const cache = new Map();       // ruta -> { t, status, headers, cuerpo }
const refrescando = new Set(); // rutas con una actualización en curso en esta instancia

const anonimo = request => request.method === "GET" && !request.headers.get("Cookie");

function pedirOrigen(request, url) {
  const destino = new URL(url.pathname + url.search, ORIGEN);
  return fetch(new Request(destino, request), { redirect: "manual" });
}

async function actualizar(request, url, clave) {
  const r = await pedirOrigen(request, url);
  if (r.status !== 200 || r.headers.get("Set-Cookie")) return r;
  const item = { t: Date.now(), status: 200, headers: [...r.headers], cuerpo: await r.arrayBuffer() };
  if (cache.size > 200) cache.clear();
  cache.set(clave, item);
  return respuestaDe(item);
}

const respuestaDe = item => new Response(item.cuerpo, { status: item.status, headers: item.headers });

async function lecturaCompartida(request, url, ctx, regla) {
  const clave = url.pathname + url.search;
  const item = cache.get(clave);
  const edad = item ? Date.now() - item.t : Infinity;
  if (edad < regla.fresco) return respuestaDe(item);
  if (edad < regla.viejo) {
    if (!refrescando.has(clave)) {
      refrescando.add(clave);
      ctx.waitUntil(actualizar(request, url, clave).catch(() => {}).finally(() => refrescando.delete(clave)));
    }
    return respuestaDe(item);
  }
  return actualizar(request, url, clave);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname.startsWith("/static/") || (url.pathname === "/" && anonimo(request)))) {
      return env.ASSETS.fetch(request);
    }
    let respuesta;
    try {
      const regla = anonimo(request) && LECTURAS.find(l => l.re.test(url.pathname));
      respuesta = regla ? await lecturaCompartida(request, url, ctx, regla) : await pedirOrigen(request, url);
    } catch (e) {
      return new Response("El servidor de AlertAR no responde. Probá de nuevo en unos minutos.", {
        status: 502, headers: { "Content-Type": "text/plain; charset=utf-8" }
      });
    }
    // Las redirecciones del servidor apuntan a su URL de Funnel: se reescriben a pages.dev.
    const location = respuesta.headers.get("Location");
    if (location && location.startsWith(ORIGEN)) {
      const r = new Response(respuesta.body, respuesta);
      r.headers.set("Location", location.slice(ORIGEN.length) || "/");
      return r;
    }
    return respuesta;
  }
};
