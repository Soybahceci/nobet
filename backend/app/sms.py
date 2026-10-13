"""
NÖBET — SMS kanalı ve sağlayıcı ön ayarları
============================================

⚠️ TASARIM KARARI — neden sağlayıcı başına sabit kod YOK

Her sağlayıcı için gövdesi koda gömülü bir adaptör yazmak cazip ama kırılgan:
parametre adı yanlış hatırlanırsa ya da sağlayıcı API'sini değiştirirse
sistem sessizce çalışmaz ve hata geç fark edilir.

Bunun yerine: **yapılandırılabilir HTTP adaptörü + ön ayarlar.**
Ön ayar seçilince alanlar dolu gelir ama arayüzde **görünür ve
düzenlenebilir** kalır. Sağlayıcı bir alan adını değiştirirse kod
değişmez, ayar güncellenir.

🔴 ÖNEMLİ: Aşağıdaki ön ayarlar **başlangıç noktasıdır**, kesin doğru
kabul edilmemelidir. Devreye almadan önce sağlayıcının güncel
dokümantasyonuyla karşılaştırılmalı ve "Test SMS gönder" ile doğrulanmalıdır.

Türkiye'de ayrıca **onaylı gönderici başlığı** ve İYS kaydı gerekir;
bunlar teknik değil evrak süreçleridir.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("nobet.sms")

# Şablonlarda kullanılabilecek yer tutucular
# {user} {pass} {sender} {to} {text}
PRESETS: dict[str, dict[str, Any]] = {
    "netgsm": {
        "label": "NetGSM",
        "method": "POST",
        "url": "https://api.netgsm.com.tr/sms/send/get",
        "content_type": "form",
        "body": {
            "usercode": "{user}",
            "password": "{pass}",
            "gsmno": "{to}",
            "message": "{text}",
            "msgheader": "{sender}",
        },
        "success_contains": "00",
        "notes": "msgheader onaylı gönderici başlığı olmalı.",
    },
    "iletimerkezi": {
        "label": "İleti Merkezi",
        "method": "POST",
        "url": "https://api.iletimerkezi.com/v1/send-sms/get",
        "content_type": "form",
        "body": {
            "username": "{user}",
            "password": "{pass}",
            "text": "{text}",
            "receipents": "{to}",
            "sender": "{sender}",
        },
        "success_contains": "200",
        "notes": "Alan adları hesap tipine göre değişebilir, doğrulayın.",
    },
    "verimor": {
        "label": "Verimor",
        "method": "POST",
        "url": "https://sms.verimor.com.tr/v2/send.json",
        "content_type": "json",
        "body": {
            "username": "{user}",
            "password": "{pass}",
            "source_addr": "{sender}",
            "messages": [{"msg": "{text}", "dest": "{to}"}],
        },
        "success_contains": "",
        "notes": "JSON gövde; yanıt olarak kampanya kimliği döner.",
    },
    "mutlucell": {
        "label": "Mutlucell",
        "method": "POST",
        "url": "https://smsgw.mutlucell.com/smsgw-ws/sndblkex",
        "content_type": "form",
        "body": {
            "ka": "{user}",
            "pwd": "{pass}",
            "org": "{sender}",
            "msg": "{text}",
            "no": "{to}",
        },
        "success_contains": "",
        "notes": "XML tabanlı uçları da var; hesabınıza uygun olanı seçin.",
    },
    "vatansms": {
        "label": "Vatan SMS",
        "method": "POST",
        "url": "https://api.vatansms.net/api/v1/1toN",
        "content_type": "json",
        "body": {
            "api_id": "{user}",
            "api_key": "{pass}",
            "sender": "{sender}",
            "message_type": "normal",
            "message": "{text}",
            "phones": ["{to}"],
        },
        "success_contains": "",
        "notes": "api_id/api_key panelden alınır.",
    },
    "generic": {
        "label": "Diğer (elle yapılandır)",
        "method": "POST",
        "url": "",
        "content_type": "json",
        "body": {},
        "success_contains": "",
        "notes": "Listede olmayan sağlayıcı için alanları elle doldurun.",
    },
}


def _fill(value: Any, ctx: dict[str, str]) -> Any:
    """Şablon yer tutucularını yineleyerek doldurur (iç içe yapılar dahil)."""
    if isinstance(value, str):
        out = value
        for k, v in ctx.items():
            out = out.replace("{" + k + "}", v)
        return out
    if isinstance(value, dict):
        return {k: _fill(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, ctx) for v in value]
    return value


class SmsSendError(RuntimeError):
    pass


async def send_sms(
    config: dict[str, Any], secret: dict[str, str], to: str, text: str,
) -> str:
    """
    Yapılandırmaya göre SMS gönderir. Yanıt gövdesini döndürür.
    Hata durumunda `SmsSendError` fırlatır — işçi yeniden dener.
    """
    url = (config.get("url") or "").strip()
    if not url:
        raise SmsSendError("SMS sağlayıcı adresi tanımlı değil")

    ctx = {
        "user": secret.get("user", ""),
        "pass": secret.get("password", ""),
        "sender": config.get("sender", ""),
        "to": to,
        "text": text,
    }

    method = (config.get("method") or "POST").upper()
    body = _fill(config.get("body") or {}, ctx)
    headers = _fill(config.get("headers") or {}, ctx)
    content_type = config.get("content_type") or "json"

    try:
        async with httpx.AsyncClient(timeout=25.0) as c:
            if method == "GET":
                r = await c.get(url, params=body, headers=headers)
            elif content_type == "form":
                r = await c.post(url, data=body, headers=headers)
            else:
                r = await c.post(url, json=body, headers=headers)
    except Exception as exc:
        raise SmsSendError(f"sağlayıcıya ulaşılamadı: {exc}") from exc

    text_out = r.text[:500]

    if r.status_code >= 400:
        raise SmsSendError(f"HTTP {r.status_code}: {text_out}")

    # Bazı sağlayıcılar hatayı da HTTP 200 ile döndürür; beklenen imza
    # tanımlıysa gövdede aranır.
    expect = (config.get("success_contains") or "").strip()
    if expect and expect not in r.text:
        raise SmsSendError(f"beklenen yanıt bulunamadı ('{expect}'): {text_out}")

    return text_out
