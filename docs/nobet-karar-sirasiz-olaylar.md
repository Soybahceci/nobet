# Karar: Sırasız olaylar ve oturum kurgusu

**Tarih:** 2026-08-11 · **Karar veren:** Claude (kullanıcı onayıyla, gece
oturumu) · **Etkilediği dilim:** 13a-3 (kenar servisi)

> ⚠️ Bu karar **kullanıcı onayına açıktır.** Gerekçesi aşağıda; katılmıyorsanız
> B seçeneğine dönmek 13a-3'ün senkron döngüsünü değiştirmeyi gerektirir,
> şemayı değil.

---

## Sorun

Oturum motoru (`sessions.apply`) olayların **kronolojik geldiğini** varsayıyor:
kişi için açık oturum varsa kapatır, yoksa yeni açar. Kenar cihazı devreye
girince bu varsayım kırılabilir — kesinti sonrası kuyruk boşalırken eski
olaylar, o sırada işlenmiş yeni olayların ardından gelir.

Tek kullanımlık veritabanında ölçüldü. Gerçek sıra 09:00 giriş → 10:00 giriş
→ 14:00 çıkış iken, işlenme sırası 10:00 → 14:00 → 09:00 olunca:

```
giriş 09:00 | çıkış —      | open     ← askıda kaldı
giriş 10:00 | çıkış 14:00  | closed   ← 4 saat (yanlış eşleşme)
```

09:00 kaydı geldiğinde 10:00–14:00 oturumu çoktan kapanmıştı; açık oturum
bulunamadığı için **yeni ve sonsuza kadar açık** bir oturum açıldı.

---

## İki seçenek

### A) Kesinlikle sıralı boşaltma — **SEÇİLEN**

Kenar kuyruğu **FIFO** ve daima en eskiden başlayarak boşalır; bir toplu
istek kabul edilmeden sonraki gönderilmez.

**Neden yeterli:** olaylar kuyruğa **oluş sırasıyla** giriyor. FIFO bir
kuyruk, çıkışta da o sırayı koruyor. Yani sırasızlık, kenar doğru
uygulandığı sürece **hiç oluşmuyor** — yukarıdaki testte sırayı ben elle
bozdum, gerçek bir kuyruk bunu üretmez.

**Bedeli:** uzun bir kesintiden sonra biriken kuyruk boşalırken canlı
olaylar da sıranın sonunda bekler. 3000 olay/gün ölçeğinde bu saniyeler
mertebesinde: 500'lük toplu isteklerle 3 saatlik bir kesinti (≈400 olay)
tek istekte akar.

**Riski ve nasıl görünür kalıyor:** buna rağmen sıra bozulursa (iki kenar
cihazı, kenarda NTP saati geri alması), askıda kalan oturum **görünmez
değil** — gece otomatik kapatma onu `auto_closed` yapıyor ve koç panelinde
**"eksik çıkış"** olarak listeleniyor. Yani hata sessizce veri bozmuyor,
insanın önüne düşüyor.

### B) Geriye dönük oturum yeniden türetme — reddedildi

Bulut olayları her sırada kabul eder; etkilenen kişi-mekân için o günün
oturumları **baştan hesaplanır**.

**Neden reddedildi:** oturumların düzeltilebilir olması Faz 0'ın kararı ve
bu doğru; ama yeniden türetme, elle yapılmış düzeltmeleri
(`SessionState.corrected`, `corrected_by`) ezme riski taşıyor. Bir yöneticinin
düzelttiği çıkış saatinin, geç gelen bir senkronla sessizce değişmesi,
çözdüğünden büyük bir sorun doğurur. Ayrıca bildirimler zaten gönderilmiş
olur — geri alınamaz.

B, A yetersiz kaldığında (birden fazla kenar cihazı) tekrar masaya gelir.

---

## Uygulanan yan düzeltme (seçenekten bağımsız, zaten gerekliydi)

`sessions.is_duplicate_read` **sıradan bağımsız** hâle getirildi.

Eskiden kişinin o mekândaki **en yeni** okumasına bakıp
`(effective_ts - last) < window` diyordu. Gelen olay daha eskiyse fark
negatif çıkıyor, negatif sayı her zaman pencereden küçük olduğu için olay
`duplicate` sayılıyor ve **oturum üretmiyordu.**

Yani zaman damgası geriye giden her olay sessizce yutuluyordu — kuyruk
boşalırken, iki okuyucunun saatleri farklıysa, NTP saati geri aldığında.
Sonuç: öğrencinin girişi yoklamada hiç görünmez.

Artık kıyaslama yalnızca **gelen olaydan önceki** okumalarla yapılıyor
(`Event.effective_ts <= effective_ts` + `max`). Doğrulandı:

| Senaryo | Sonuç |
|---|---|
| 3 sn arayla iki okuma | ikincisi `duplicate` — koruma bozulmadı |
| Eski damgalı olay sonradan | `granted` **ve oturum üretti** (eskiden yutuluyordu) |
| Eski olaydan 5 sn sonraki | `duplicate` — pencere zamana göre, sıraya göre değil |

---

## 13a-3 için bağlayıcı kurallar

1. Kuyruk **FIFO**; `id` sırasına göre okunur, atlanmaz.
2. Aynı anda **tek** toplu istek uçar; yanıt gelmeden sonraki gönderilmez.
3. `accepted` ve `duplicate` kuyruktan silinir, `rejected` **ölü mektuba**
   taşınır (§3.1b) — hiçbir koşulda kuyrukta bırakılmaz.
4. Kenar saati NTP ile geri alınırsa, o ana kadar kuyrukta bekleyen
   olayların damgası **değiştirilmez**; `clock_unsynced` bayrağı taşınır.
