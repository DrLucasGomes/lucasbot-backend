const SUPABASE_URL = "https://gwxcnczuwfrswhkzflaw.supabase.co";
const TRACKING_TABLE = "click_sessions";
const TTL_MINUTES = 30;

function interpretarCodigo(codigo) {
  const texto = String(codigo || "").trim().toLowerCase();
  const match = texto.match(/^(yt|fb|ig)(\d+)$/);
  if (!match) return null;

  const [, canal, numero] = match;
  const nomes = { yt: "YouTube", fb: "Facebook", ig: "Instagram" };
  const origem = nomes[canal];

  return {
    origem,
    campanha: `Vigor_${canal.toUpperCase()}_${numero}`,
    video: numero,
    produto: "Protocolo Vigor 360",
    utm_source: origem.toLowerCase(),
    utm_medium: "social",
    utm_campaign: `vigor_${canal}_${numero}`,
    utm_content: texto,
    utm_term: null,
  };
}

function tokenUrlSafe(bytes = 9) {
  const data = new Uint8Array(bytes);
  crypto.getRandomValues(data);
  let bin = "";
  for (const b of data) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256Hex(texto) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(texto));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function limparNumero(numero) {
  return String(numero || "").replace(/\D/g, "");
}

function urlWhatsApp(numero, token) {
  const texto = encodeURIComponent(`VIGOR ${token}`);
  return `https://wa.me/${limparNumero(numero)}?text=${texto}`;
}

async function salvarClick(env, registro) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1800);
  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/${TRACKING_TABLE}`, {
      method: "POST",
      headers: {
        apikey: env.SUPABASE_KEY,
        Authorization: `Bearer ${env.SUPABASE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(registro),
      signal: controller.signal,
    });
    return r.ok;
  } catch (_) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/(?:r\/)?([^/]+)\/?$/i);

    if (!match) return new Response("Not found", { status: 404 });
    if (!env.WHATSAPP_NUMBER || !env.SUPABASE_KEY || !env.TRACKING_IP_SALT) {
      return new Response("Worker not configured", { status: 503 });
    }

    const meta = interpretarCodigo(match[1]);
    if (!meta) return new Response("Invalid tracking code", { status: 404 });

    const agora = new Date();
    const expira = new Date(agora.getTime() + TTL_MINUTES * 60 * 1000);
    const token = tokenUrlSafe();
    const ip = request.headers.get("cf-connecting-ip") || "";
    const ipHash = ip ? await sha256Hex(`${env.TRACKING_IP_SALT}:${ip}`) : null;

    const registro = {
      id: crypto.randomUUID(),
      token,
      ...meta,
      manychat_id: null,
      lead_id: null,
      claimed: false,
      claim_method: null,
      claim_confidence: null,
      user_agent: request.headers.get("user-agent"),
      ip_hash: ipHash,
      created_at: agora.toISOString(),
      expires_at: expira.toISOString(),
      claimed_at: null,
    };

    const salvo = await salvarClick(env, registro);
    const headers = new Headers({
      Location: urlWhatsApp(env.WHATSAPP_NUMBER, token),
      "Cache-Control": "no-store",
      "X-Lucas-Tracking": salvo ? "saved" : "degraded",
    });

    // Fail-open: mesmo se o Supabase falhar, o usuario segue para o WhatsApp.
    return new Response(null, { status: 302, headers });
  },
};
