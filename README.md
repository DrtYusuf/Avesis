# AVESİS Duyuru Takip Botu

Bu bot, belirtilen AVESİS profesör profillerini her gün otomatik olarak kontrol eder ve yeni duyurular bulunduğunda Telegram üzerinden bildirim gönderir.

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
PROFESSORS=https://avesis.gazi.edu.tr/hocakullanicisi,https://avesis.ankara.edu.tr/digerhoca
CHECK_TIME=09:00
```

> **Not:** `PROFESSORS` alanına virgülle ayırarak birden fazla AVESİS profil URL'si girebilirsiniz.

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

---

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

## Dosya Yapısı

```
avesis-tracker/
├── main.py          # Ana giriş noktası, zamanlayıcı
├── tracker.py       # AVESİS sayfa kazıma (scraping) mantığı
├── bot.py           # Telegram bot entegrasyonu
├── storage.py       # Görülen duyuruların JSON depolanması
├── config.py        # Yapılandırma yönetimi
├── requirements.txt # Python bağımlılıkları
├── .env.example     # Örnek ortam değişkenleri
├── .env             # Gerçek ortam değişkenleri (git'e eklemeyin!)
├── data/
│   └── seen.json    # Görülen duyuru kayıtları (otomatik oluşturulur)
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

---

## Notlar

- `data/seen.json` dosyası silinirse bot tüm mevcut duyuruları yeniden "yeni" olarak algılar.
- `.env` dosyasını asla Git'e göndermeyin. `.gitignore`'a ekleyin.
- AVESİS sayfa yapısı üniversiteden üniversiteye farklılık gösterebilir.
