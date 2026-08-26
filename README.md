# AVESİS Duyuru Takip Botu

Bu bot, takip ettiğiniz AVESİS hoca profillerini her gün otomatik olarak kontrol
eder ve yeni duyurular bulunduğunda Telegram üzerinden bildirim gönderir.

Takip listesini Telegram'dan [`/seç`](#seç--hoca-seçimi) komutuyla yönetirsiniz:
fakülte kadrosundan butonlarla hoca eklersiniz, dokunarak çıkarırsınız — `.env`
dosyasını elle düzenlemeniz gerekmez.

---

## Gereksinimler

- Python 3.11 veya üzeri
- İnternet bağlantısı
- Telegram hesabı

---

## Kurulum

### 1. Depoyu klonlayın veya dosyaları indirin

```bash
git clone <repo-url>
cd avesis-tracker
```

### 2. Sanal ortam oluşturun ve bağımlılıkları kurun

```bash
python3 -m venv venv
source venv/bin/activate      # Linux/macOS
# venv\Scripts\activate       # Windows

pip install -r requirements.txt
```

---

## Yapılandırma

### Adım 1 — Telegram Botu Oluşturma (@BotFather)

1. Telegram'da **@BotFather**'ı arayın ve başlatın.
2. `/newbot` komutunu gönderin.
3. Botunuza bir isim verin (örn. `AVESİS Takip Botu`).
4. Botunuza bir kullanıcı adı verin (örn. `avesis_takip_bot`). Kullanıcı adı `bot` ile bitmelidir.
5. BotFather size bir **token** verecektir. Bu token'ı kopyalayın:
   ```
   1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
   ```

### Adım 2 — Chat ID'yi Öğrenme

**Kişisel sohbet için:**
1. Oluşturduğunuz botu Telegram'da açın ve `/start` gönderin.
2. Tarayıcınızda şu URL'yi açın (token'ınızla değiştirin):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Gelen JSON'da `"chat": {"id": 123456789}` kısmındaki sayı sizin Chat ID'nizdir.

**Grup için:**
1. Botu gruba ekleyin ve gruba herhangi bir mesaj gönderin.
2. Yukarıdaki `/getUpdates` URL'sini yenileyin.
3. `"chat": {"id": -1001234567890}` şeklinde negatif bir sayı göreceksiniz. Bu grup Chat ID'sidir.

### Adım 3 — .env Dosyasını Doldurun

`.env.example` dosyasını `.env` olarak kopyalayın:

```bash
cp .env.example .env
```

Ardından `.env` dosyasını bir metin editörüyle açın ve değerleri doldurun:

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=123456789
PROFESSORS=https://avesis.yildiz.edu.tr/hocakullanicisi
CHECK_TIME=09:00
FACULTY_NAME=Elektrik-Elektronik Fakültesi
```

> **Not:** `PROFESSORS` alanına virgülle ayırarak birden fazla AVESİS profil URL'si girebilirsiniz.
> Bu alan yalnızca **başlangıç listesidir** — bot çalışırken hoca eklemek/çıkarmak için
> Telegram'dan [`/seç`](#seç--hoca-seçimi) komutunu kullanın. Listeyi tamamen `/seç` ile
> kurmak isterseniz `PROFESSORS` alanını boş bırakabilirsiniz.

### Tüm Ortam Değişkenleri

| Değişken | Zorunlu | Varsayılan | Açıklama |
|----------|---------|-----------|----------|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | @BotFather'dan alınan bot token'ı |
| `TELEGRAM_CHAT_ID` | ✅ | — | Bildirimlerin gönderileceği sohbet. `/seç` yalnızca bu sohbette çalışır |
| `PROFESSORS` | ⚠️ | — | Virgülle ayrılmış başlangıç profil listesi. `data/tracked.json` varsa gerekmez |
| `CHECK_TIME` | | `09:00` | Günlük kontrol saati (tek saat) |
| `CHECK_TIMES` | | `CHECK_TIME` | Virgülle ayrılmış birden fazla kontrol saati, örn. `09:00,15:00,21:00` |
| `TIMEZONE` | | `Europe/Istanbul` | Kontrol saatlerinin yorumlanacağı saat dilimi |
| `AVESIS_BASE_URL` | | `https://avesis.yildiz.edu.tr` | Kurumun AVESİS adresi |
| `FACULTY_NAME` | | `Elektrik-Elektronik Fakültesi` | `/seç` ile eklenebilecek hocaları bu fakülteyle sınırlar |
| `FACULTY_CACHE_TTL_HOURS` | | `24` | Fakülte kadro listesinin önbellek ömrü (saat) |
| `CHECK_SECRET` | | — | Yalnızca `server.py` için: `/check` uç noktasının Bearer token'ı |
| `PORT` | | `8080` | Yalnızca `server.py` için: HTTP sunucu portu |

`CHECK_TIMES` birden fazla kontrol yapmak isteyenler içindir; verilmezse
`CHECK_TIME` tek saat olarak kullanılır. Günlük özet her gece **22:00**'de
gönderilir (şu an sabit).

---

## Çalıştırma

### Normal Çalıştırma

```bash
source venv/bin/activate   # Sanal ortamı aktifleştirin
python main.py
```

Bot başladığında:
1. Telegram'a başlangıç bildirimi gönderir.
2. Tüm profilleri hemen bir kez kontrol eder.
3. Her gün `CHECK_TIME`'da (varsayılan: 09:00) tekrar kontrol eder.

### Arka Planda Çalıştırma (nohup)

Terminali kapatsanız bile botun çalışmaya devam etmesi için:

```bash
source venv/bin/activate
nohup python main.py > avesis-tracker.log 2>&1 &
echo "Bot PID: $!"
```

Botu durdurmak için:

```bash
# PID'yi öğrenin
ps aux | grep main.py

# Durdurun
kill <PID>
```

---

### Systemd Servisi Olarak Çalıştırma (Linux)

Sunucuda kalıcı olarak çalıştırmak için systemd servisi oluşturun:

1. Servis dosyasını oluşturun:

```bash
sudo nano /etc/systemd/system/avesis-tracker.service
```

2. Aşağıdaki içeriği yapıştırın (yolları kendi sisteminize göre düzenleyin):

```ini
[Unit]
Description=AVESİS Duyuru Takip Botu
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/avesis-tracker
ExecStart=/home/YOUR_USERNAME/avesis-tracker/venv/bin/python main.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/home/YOUR_USERNAME/avesis-tracker/avesis-tracker.log
StandardError=append:/home/YOUR_USERNAME/avesis-tracker/avesis-tracker.log

[Install]
WantedBy=multi-user.target
```

3. Servisi etkinleştirin ve başlatın:

```bash
sudo systemctl daemon-reload
sudo systemctl enable avesis-tracker
sudo systemctl start avesis-tracker
```

4. Durumu kontrol edin:

```bash
sudo systemctl status avesis-tracker
```

5. Logları canlı izleyin:

```bash
journalctl -u avesis-tracker -f
# veya
tail -f avesis-tracker.log
```

---

### HTTP ile Tetikleme (server.py)

Botu sürekli çalıştırmak yerine dışarıdan tetiklemek isterseniz (cron servisleri,
uptime izleyicileri, ücretsiz barındırma planları) `server.py` küçük bir HTTP
sunucusu açar:

```bash
python server.py
```

| Uç nokta | Yöntem | Açıklama |
|----------|--------|----------|
| `/check` | POST | Bir kontrol turu çalıştırır |
| `/health` | GET | Sağlık kontrolü |

`CHECK_SECRET` tanımlıysa `/check` çağrısı Bearer token ister:

```bash
curl -X POST https://sunucunuz/check -H "Authorization: Bearer GIZLI_ANAHTAR"
```

> **Not:** Bu mod yalnızca duyuru kontrolü yapar; Telegram komutları (`/seç`,
> `/durum`, `/kontrol`) için `main.py`'nin çalışıyor olması gerekir.

---

### Tek Seferlik Kontrol (check.py)

Bot başlatmadan tek bir kontrol turu çalıştırmak için:

```bash
python check.py
```

---

## Telegram Komutları

| Komut | Açıklama |
|-------|----------|
| `/kontrol` | Duyuruları hemen kontrol eder |
| `/durum` | Son kontrol zamanı, istatistikler ve takip edilen hoca listesi |
| `/seç` | Takip edilen hocaları butonlarla seçer (ekler / çıkarır) |
| `/seç <isim>` | Fakülte kadrosunda isme göre arar, sonuçtan doğrudan ekler |

> Telegram, komut adlarında yalnızca ASCII harfleri tanıdığı için `/seç`
> komutu **`/sec`** (ve `/secim`) olarak da çalışır. İkisi de aynı ekranı açar.

### `/seç` — Hoca Seçimi

`/seç` gönderdiğinizde inline butonlarla yönetilen bir menü açılır:

```
🎛 Hoca Seçimi

👨‍🏫 Takip edilen: 3 hoca
🏛 Eklenebilir kadro: Elektrik-Elektronik Fakültesi (205 kişi)

[ 📋 Takip Listem (3) ]
[ ➕ Hoca Ekle        ]
[ ♻️ Kadroyu Yenile ] [ ✖️ Kapat ]
```

- **📋 Takip Listem** — Şu an takip edilen hocaları listeler. Bir hocaya
  dokunmak onu takipten çıkarır.
- **➕ Hoca Ekle** — Önce bölüm seçilir, sonra o bölümdeki hocalar sayfa sayfa
  listelenir. `➕` işaretli hocaya dokunmak onu takibe alır, `✅` işaretliye
  dokunmak takipten çıkarır.
- **♻️ Kadroyu Yenile** — Fakülte personel listesini AVESİS'ten yeniden çeker.

**Eklenebilecek hocalar `FACULTY_NAME` ile sınırlıdır** (varsayılan:
Elektrik-Elektronik Fakültesi). Liste, AVESİS'in araştırmacı arama servisinden
çekilir ve `data/faculty_cache.json` dosyasında `FACULTY_CACHE_TTL_HOURS` süresi
boyunca önbelleğe alınır. Başka bir fakülteyi takip etmek isterseniz `.env`
dosyasındaki `FACULTY_NAME` değerini değiştirmeniz yeterlidir.

Takip listesi `data/tracked.json` dosyasında tutulur. `PROFESSORS` ortam
değişkeni yalnızca **ilk çalıştırmada** başlangıç listesi olarak kullanılır;
sonrasında `/seç` ile yapılan değişiklikler geçerlidir.

> **Not:** Yeni eklenen bir hocanın mevcut duyuruları ilk kontrolde sessizce
> kaydedilir; bildirim olarak yalnızca eklendikten *sonra* yayınlanan duyurular
> gönderilir. Böylece hoca eklerken eski duyuru yağmuruna tutulmazsınız.

> **Güvenlik:** `/seç` yalnızca `TELEGRAM_CHAT_ID` ile belirtilen sohbette
> çalışır; başka sohbetlerden gelen istekler reddedilir.

---

### Kontrol Mesajı

Her kontrol sonrasında bot, hangi hocaların kontrol edildiğini listeleyen bir
durum mesajı gönderir (yeni duyuru yoksa mesaj her seferinde yeniden
gönderilmez, mevcut mesaj güncellenir):

```
✅ Duyurular kontrol edildi

📭 Yeni duyuru yok.
🕐 26.08.2026 19:45

👨‍🏫 Kontrol edilenler (3):
• Prof. Dr. Ahmet KIZILAY
• Doç. Dr. Arzu KAKIŞIM
• Prof. Dr. Selami BEYHAN
```

Yeni duyuru bulunduğunda ilk satır `📢 2 yeni duyuru bulundu.` şeklinde
değişir. Bir hocanın sayfasına ulaşılamadıysa ayrı bir başlık eklenir:

```
⚠️ Ulaşılamayanlar (1):
• Dr. Öğr. Üyesi Ekrem ÇETİNKAYA
```

Aynı özet `/kontrol` komutuna verilen yanıtta ve her gece gönderilen günlük
özette de aynı biçimde gösterilir:

```
📊 Günlük Özet

📢 Bugün toplam 4 yeni duyuru bulundu.
🕐 26.08.2026 21:00

👨‍🏫 Kontrol edilenler (3):
• Prof. Dr. Ahmet KIZILAY
• Doç. Dr. Arzu KAKIŞIM
• Prof. Dr. Selami BEYHAN
```

Liste 25 hocayla sınırlıdır; fazlası `…ve N hoca daha` olarak özetlenir.

---

## Dosya Yapısı

```
avesis-tracker/
├── main.py          # Ana giriş noktası, zamanlayıcı, komut kayıtları
├── tracker.py       # AVESİS sayfa kazıma (scraping) mantığı
├── directory.py     # Fakülte personel dizini (/seç ekleme listesi)
├── selection.py     # /seç komutu ve inline buton ekranları
├── bot.py           # Telegram bot entegrasyonu
├── storage.py       # Takip listesi ve görülen duyuruların JSON depolanması
├── config.py        # Yapılandırma yönetimi
├── server.py        # HTTP ile tetiklenen kontrol (cron/uptime servisleri için)
├── check.py         # Tek seferlik kontrol betiği (bot başlatmadan)
├── requirements.txt # Python bağımlılıkları
├── .env.example     # Örnek ortam değişkenleri
├── .env             # Gerçek ortam değişkenleri (git'e eklemeyin!)
├── data/
│   ├── seen.json           # Görülen duyuru kayıtları (otomatik)
│   ├── tracked.json        # /seç ile yönetilen takip listesi (otomatik)
│   ├── faculty_cache.json  # Fakülte kadro önbelleği (otomatik)
│   ├── professor_names.json # Hoca adı önbelleği (otomatik)
│   └── stats.json          # İstatistikler (otomatik)
└── avesis-tracker.log  # Log dosyası (otomatik oluşturulur)
```

---

## Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| `TELEGRAM_BOT_TOKEN is not set` | `.env` dosyasını kontrol edin |
| `Unauthorized` hatası | Bot token'ının doğruluğunu kontrol edin |
| `Chat not found` hatası | Chat ID'nin doğruluğunu kontrol edin, botu sohbete ekleyin |
| Duyurular gelmiyor | AVESİS profil URL'lerinin doğru olduğunu kontrol edin |
| `Duyurular bölümü bulunamadı` | Profilin "Duyurular" sekmesinin mevcut olduğunu kontrol edin |
| `/seç` yanıt vermiyor | Komutu `TELEGRAM_CHAT_ID`'deki sohbetten gönderdiğinizden emin olun |
| `/seç` "personel listesi alınamadı" diyor | AVESİS'e ulaşılamıyor; `AVESIS_BASE_URL` doğru mu, birazdan tekrar deneyin |
| `/seç` listesi boş | `FACULTY_NAME` değerinin AVESİS'teki fakülte adıyla birebir aynı olduğunu kontrol edin |

---

## Notlar

- `data/seen.json` dosyası silinirse bot takip edilen profilleri sıfırdan baz alır (duyuru yağmuru olmaz, sessizce kaydedilir).
- `data/tracked.json` dosyası silinirse takip listesi `PROFESSORS` değerinden yeniden oluşturulur.
- `.env` dosyasını asla Git'e göndermeyin. `.gitignore`'a ekleyin.
- AVESİS sayfa yapısı üniversiteden üniversiteye farklılık gösterebilir.
