#!/usr/bin/env bash
# NÖBET — uygulama veritabanı rolünü açar (Faz 13b-3, mimari §10.8)
#
# Uygulama veritabanına SÜPER KULLANICI olarak bağlanıyordu. Bu betik
# süper olmayan `nobet_app` rolünü açar, parolasını üretir, `.env`e yazar.
# Yetkileri migration 0018 verir.
#
# Çalıştırılabilir; tekrar çalıştırmak zararsız (parola varsa dokunmaz).
#
#   cd <NÖBET dizini> && ./nobet-app-rolu-ac.sh
#   docker compose up -d --force-recreate api ingest
#
# ⚠️ Bu bir OPERASYON betiği; kurum kullanmaz. "Sıfır CLI" kuralı kurumun
# günlük işleri içindir, kurulum adımları için değil.
set -euo pipefail

ROL=nobet_app
ENV_DOSYA="${ENV_DOSYA:-.env}"
KAP="${KAP:-nobet-postgres}"

[ -f "$ENV_DOSYA" ] || { echo "HATA: $ENV_DOSYA yok. Yığın dizininde çalıştırın."; exit 1; }

# shellcheck disable=SC1090
SAHIP=$(grep -E '^POSTGRES_USER=' "$ENV_DOSYA" | cut -d= -f2-)
VT=$(grep -E '^POSTGRES_DB=' "$ENV_DOSYA" | cut -d= -f2-)
[ -n "$SAHIP" ] && [ -n "$VT" ] || { echo "HATA: POSTGRES_USER/POSTGRES_DB okunamadı."; exit 1; }

psql() { docker exec -i "$KAP" psql -U "$SAHIP" -d "$VT" -v ON_ERROR_STOP=1 "$@"; }

# --- parola: varsa korunur ------------------------------------------------
# Yeniden üretmek, çalışan uygulamanın bağlantısını koparırdı.
MEVCUT=$(grep -E '^POSTGRES_APP_PASSWORD=' "$ENV_DOSYA" | cut -d= -f2- || true)
if [ -n "$MEVCUT" ]; then
    PAROLA="$MEVCUT"
    echo "· .env'de parola zaten var, korunuyor."
else
    PAROLA=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)
    echo "· yeni parola üretildi."
fi

# --- rol -------------------------------------------------------------------
# NOSUPERUSER/NOCREATEDB/NOCREATEROLE açıkça yazılıyor: varsayılan olsa da
# niyetin belgesi burada. Bu satırların değişmesi bu fazın iptali demektir.
psql <<SQL
DO \$\$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ROL') THEN
        ALTER ROLE $ROL WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
             PASSWORD '$PAROLA';
    ELSE
        CREATE ROLE $ROL WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
             PASSWORD '$PAROLA';
    END IF;
END
\$\$;
-- Veritabanına bağlanabilsin, ama şemada nesne YARATAMASIN.
GRANT CONNECT ON DATABASE "$VT" TO $ROL;
REVOKE CREATE ON SCHEMA public FROM $ROL;
SQL

# --- .env ------------------------------------------------------------------
yaz() {
    if grep -qE "^$1=" "$ENV_DOSYA"; then
        sed -i "s|^$1=.*|$1=$2|" "$ENV_DOSYA"
    else
        # ⚠️ .env son satirinda newline OLMAYABILIR. Kontrol etmeden
        # eklemek satirlari birlestirir: 2026-08-13'te SETTINGS_KEY'in
        # degerine POSTGRES_APP_USER yapisti ve API acilamadi.
        [ -s "$ENV_DOSYA" ] && [ "$(tail -c1 "$ENV_DOSYA" | wc -l)" -eq 0 ] \
            && printf '\n' >> "$ENV_DOSYA"
        printf '%s=%s\n' "$1" "$2" >> "$ENV_DOSYA"
    fi
}
cp -a "$ENV_DOSYA" "$ENV_DOSYA.yedek.$(date +%Y%m%d%H%M%S)"
yaz POSTGRES_APP_USER "$ROL"
yaz POSTGRES_APP_PASSWORD "$PAROLA"

echo
echo "✓ $ROL rolü hazır, .env güncellendi (yedeği alındı)."
psql -tA -c "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname='$ROL';"
echo
echo "Sırada:"
echo "  docker compose up -d --force-recreate api ingest"
echo "  # migration 0018 yetkileri verir; api açılışta kendisi koşturur."
