"""
NÖBET — Ayarlar
================
Her şey ortam değişkeninden okunur. Kodda hiçbir sır gömülü değil.
Kontrat: docs/nobet-faz1-sistem-sozlesmesi.md
"""
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Uygulama ---
    app_name: str = "NOBET API"
    api_prefix: str = "/api/v1"
    debug: bool = False
    timezone: str = "Europe/Istanbul"

    # --- PostgreSQL ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "nobet"
    postgres_user: str = "nobet"
    postgres_password: str

    # --- Uygulama rolü (Faz 13b-3) ---------------------------------------
    # ⚠️ Uygulama veritabanına SÜPER KULLANICI olarak bağlanıyordu (2026-08-13
    # tespiti): 91 tablonun sahibi, `usesuper=t`. API'deki bir açık — kapatılan
    # dizin aşımı gibi — tüm veritabanında sınırsız yetki demekti: tablo
    # silme, her şeyi okuma, `COPY ... TO PROGRAM` ile komut çalıştırma.
    #
    # Artık ikiye ayrılıyor:
    #   · uygulama  → `postgres_app_user`  (süper DEĞİL, yalnızca DML)
    #   · migration → `postgres_user`      (sahip, DDL yapar)
    #
    # Boş bırakılırsa eski davranış sürer — geri uyumluluk için, ama
    # üretimde MUTLAKA doldurulmalı.
    postgres_app_user: str = ""
    postgres_app_password: str = ""

    # --- MQTT (kontrat §2.1) ---
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_pass: str = ""
    # Kalıcı oturum: Faz 3'te, abone yokken yayınlanan olayların broker
    # tarafından düşürüldüğünü gördük. clean_start=False + kalıcı client_id
    # ile ingest yeniden başlasa bile aradaki mesajlar kaybolmaz.
    mqtt_client_id: str = "nobet-ingest"
    mqtt_topic_prefix: str = "nobet/v1"

    # --- Kimlik doğrulama (§3.1) ---
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14

    # --- Refresh token çerezi (denetim O-1/D-3) ---
    # Refresh token artık HttpOnly çerezde; JavaScript okuyamaz, dolayısıyla
    # bir XSS açığı uzun ömürlü kimlik bilgisini çalamaz.
    #
    # ⚠️ `Secure` bayrağı HTTPS ZORUNLU kılar. Bugün panel yerel ağda düz
    # HTTP çalıştığı için varsayılan `false`; açık olsaydı tarayıcı çerezi
    # hiç göndermez ve kimse giriş yapamazdı.
    # **Faz 13f'te HTTPS'e geçilince true yapılmalı.**
    cookie_secure: bool = False
    cookie_name: str = "nobet_refresh"

    # --- İş kuralları ---
    # §4.1: turnikeye yaslanma koruması
    duplicate_window_seconds: int = 10
    # §3.4: enrollment ekranının varsayılan penceresi
    enroll_window_seconds: int = 60

    # --- Bildirim (Faz 8) ---
    # "dryrun" | "whatsapp". Kanal hazır değilken dryrun: mesaj üretilir,
    # kuyruğa girer, loglanır ama gönderilmez.
    notify_channel: str = "dryrun"
    wa_gateway_url: str = "http://wa-gateway:3000"
    notify_max_attempts: int = 5
    default_country_code: str = "90"

    # --- Parola e-postaları (v1.7) ---
    # Sıfırlama bağlantısının önüne konan adres. Kullanıcı bu bağlantıya
    # KENDİ tarayıcısından tıklayacak, o yüzden konteyner içi adres değil,
    # dışarıdan erişilen adres olmalı (ör. http://nobet.local:8080).
    # Yanlışsa e-posta gider ama bağlantı açılmaz.
    public_base_url: str = "http://localhost:8080"

    # --- WhatsApp sohbet ---
    # Ağ geçidi gelen mesajları bu sırla imzalar. Ağ geçidi ile API aynı
    # docker ağında ama yine de doğrulanır: konteyner ağına sızan bir şey
    # sahte "veli mesajı" uydurup otomatik yanıt tetikleyebilirdi.
    # Ayarlardaki sağlayıcı kimlik bilgilerini şifreler (Fernet anahtarı).
    # Tanımlı değilse sır saklanmaz — düz metin yazmaktansa reddedilir.
    settings_key: str = ""

    wa_webhook_secret: str = ""
    # Anlaşılmayan mesajlarda haber verilecek yönetici numarası (boşsa
    # yalnızca panelde işaretlenir, mesaj gönderilmez)
    admin_whatsapp: str = ""

    # --- CORS (denetim O-1) ---
    # Varsayılan BOŞ. Arayüz API ile aynı kökenden servis ediliyor
    # (FastAPI static olarak sunuyor), dolayısıyla normal kullanımda
    # çapraz köken isteği HİÇ yok ve CORS'a gerek yok.
    #
    # Eski varsayılan `["*"]` idi ve `allow_credentials=True` ile
    # birleşiyordu; bu ikisi şartnameye göre birlikte geçersiz. Ayrı bir
    # alan adından arayüz servis edilecekse buraya AÇIKÇA yazılmalı.
    cors_origins: list[str] = Field(default_factory=list)

    # --- API dokümanı (denetim O-4) ---
    # `/docs` ve `/openapi.json` kimlik doğrulaması istemez; açık bırakılırsa
    # saldırgana tüm uç haritasını, alan adlarını ve rol gereksinimlerini
    # hazır verir. Yerel ağda önemsiz, internette değil.
    # Varsayılan olarak `debug` ile birlikte açılır.
    docs_enabled: bool = False

    def _url(self, user: str, password: str) -> str:
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def database_url(self) -> str:
        """UYGULAMANIN bağlantısı — süper olmayan rol (varsa)."""
        return self._url(
            self.postgres_app_user or self.postgres_user,
            self.postgres_app_password or self.postgres_password,
        )

    @computed_field
    @property
    def migration_database_url(self) -> str:
        """
        DDL bağlantısı — tabloların SAHİBİ.

        Migration'lar tablo yaratır/değiştirir; uygulama rolünün bu yetkisi
        YOKTUR ve olmamalıdır. Ayrım tam olarak bunun için.
        """
        return self._url(self.postgres_user, self.postgres_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
