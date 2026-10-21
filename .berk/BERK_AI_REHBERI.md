# Berk Dili — Yapay Zekâ Asistanı Referansı (BERK_AI_REHBERI)

> **Amaç:** Berk dilini bilmeyen bir VS Code YZ asistanının (Copilot, Claude, Cursor, Gemini, Kimi…)
> **doğru, derlenebilir Berk kodu** yazabilmesi için gereken çekirdek bilgi. Bu belge Berk derleyici
> kaynağından ve **gerçek, derlenen stdlib kodundan** doğrulanmıştır (dokümandan değil koddan).
> Belge dili Türkçe (kanonik); İngilizce eş anahtar kelimeler parantez içinde verilmiştir.
>
> **Kapsam notu:** Bu rehber son-kullanıcı dil çekirdeğini kapsar. Sektör kütüphaneleri
> (savunma/uzay/radar) ve spektral/Radar katmanları **bilerek dışarıda bırakılmıştır** — bunlar lisanslı
> paketlerdir; adları §15'te, edinme yolu `BPM_KULLANIM_REHBERI.md` §7'de, iletişim: https://berk-tech.com/iletisim.html.
>
> **Bu dosya uzantıyla gelir** ve uzantı onu her indeks tazelemesinde çalışma alanına
> **`.berk/BERK_AI_REHBERI.md`** olarak kopyalar (AI araçları çalışma alanı dışını okuyamayabilir).
> Paket durumu için önce **`.berk/EGITIM_DURUM.md`**'yi oku (§16, §16.5).

---

## 0. Berk nedir — 30 saniyelik özet

Berk, Rust düzeyinde bellek/eşzamanlılık güvenliği hedefleyen, **iki dilli (Türkçe/İngilizce)**,
sertifikasyon-sınıfı (DO-178C / ISO 26262 / IEC 62304) bir **sistem programlama dilidir**.

Bir YZ'nin bilmesi gereken **tek en önemli kural**:

> **Berk blokları süslü parantez `{ }` DEĞİL, `yap … son` (do … end) ile yazılır.**
> Satır sonu ifadeyi bitirir; noktalı virgül gerekmez.

Kod **tek kanonik biçimdedir: Türkçe**. Parser İngilizce anahtar kelimeleri de kabul eder
(`function`/`return`/`if`…), ama üretilen kod Türkçe anahtar kelimelerle yazılmalıdır.

---

## 1. Blok yapısı, yorumlar, giriş noktası

```berk
// Tek satır yorum
/// Doküman yorumu (fonksiyon/tip üstünde) — [REQ-XXX-000] izlenebilirlik etiketi eklenebilir

// Program giriş noktası: ana()  (main de kabul edilir)
fonksiyon ana() -> sayı yap
    yazdır("Merhaba, Berk!")
    döndür 0
son
```

- Blok açan: `yap` (do). Blok kapatan: `son` (end). **Her `yap` bir `son` ile kapanır.**
- `yazdır(...)` = ekrana yaz (print).
- `döndür X` = değer döndür (return).
- Dosya adı uzantısı: `.berk` (veya `.brk`).

---

## 2. Anahtar kelime sözlüğü (kanonik TR | İngilizce | anlam)

| Türkçe (kanonik) | English | Anlam |
|---|---|---|
| `yap` … `son` | `do` … `end` | blok aç / kapat |
| `fonksiyon` | `function` / `fn` | fonksiyon |
| `saf fonksiyon` | `pure function` | saf (yan-etkisiz) fonksiyon |
| `döndür` | `return` | değer döndür |
| `değişken` | `let` / `var` | değişken tanımı (yeniden atanabilir) |
| `sabit` | `const` | sabit |
| `pub` / `açık` | `pub` | dışa açık (public) |
| `eğer` … `ise` | `if` … `then` | koşul |
| `değilse` | `else` | aksi hâlde |
| `değilse eğer` / `veya eğer` | `else if` / `elif` | koşul zinciri (else-if) |
| `iken` | `while` | döngü |
| `her biri` … `içinde` | `for … in` | her-eleman döngüsü |
| `eşleştir` | `match` | desen eşleme |
| `dur` | `break` | döngüden çık |
| `geç` | `continue` | sonraki tura geç |
| `tip` | `type` | tip takma adı / tanımı |
| `yapı` | `struct` | yapı (kayıt) |
| `numaralama` | `enum` | numaralandırma |
| `modül` | `module` | modül bildirimi |
| `kullan` | `use` / `import` | modül içe aktar |
| `ve` / `veya` / `değil` | `and` / `or` / `not` | mantıksal operatörler |
| `doğru` / `yanlış` | `true` / `false` | boolean |
| `dene` / `yakala` | `try` / `catch` | hata yakalama |
| `asenkron` / `bekle` | `async` / `await` | eşzamansızlık |

> **Doğrulama notu:** Anahtar kelime çözümü lexer'da (`src/lexer/lexer.rs`, `lookup_ident`) yapılır.
> `keywords.toml` henüz lexer'a tam entegre DEĞİLDİR; yukarıdaki tablo gerçek derlenen kodla
> çapraz doğrulanmıştır. Emin olmadığın bir kelimeyi ad olarak kullanma (bkz. §12).

---

<!-- EN-TAKMA-AD-SOZLESMESI -->
### 2.1 İngilizce kod: anahtar kelimeler + stdlib İngilizce takma adları (EN aliases)

TR — **uluslararası kullanım için bağlayıcı kurallar:**

- Berk iki dillidir. Yukarıdaki İngilizce anahtar kelimeler (`use`, `function`, `let`, `if … then do … end`,
  `return`, `int`) Türkçe karşılıklarıyla AYNI derlenir; ikisi aynı dosyada karışabilir.
- Stdlib fonksiyonlarının (çekirdek + genel BPM paketleri) **İngilizce takma adları** vardır. Takma ad, Türkçe
  asılı çağıran ince bir sarmalayıcıdır: davranış, parametre sırası ve dönüş tipi BİREBİR aynıdır. Kaynakta her
  modülün `İNGİLİZCE TAKMA ADLAR / ENGLISH ALIASES` bölümündedir.
- Kullanıcı İngilizce yazıyor ya da İngilizce kod istiyorsa: İngilizce anahtar kelimeleri ve takma adları kullan.
  Türkçe yazıyorsa Türkçe asılları kullan.
- **Takma adı TAHMİN ETME.** Adlar modüller arası çakışmayı önlemek için çoğu zaman öneklidir: `string::str_len`
  (`uzunluk_yazı`), `istatistik::istats_mean` (`ortalama`), `json::json_number` (`json_sayı`), `audio::vad_create`
  (`vad_olustur`). Doğru adı kütüphanenin eğitim belgesindeki "İngilizce takma adlar / English aliases" bölümünden
  (`en`↔`tr` çiftleri) al: `egitim_oku <lib>`. Belgede yoksa Türkçe asılı kullan, İngilizce ad uydurma.
- Takma ad yalnız FONKSİYONLAR içindir: yapı (struct) adları, alan adları ve tip takma adları kütüphanede nasıl
  tanımlıysa öyle kalır. Yerleşik metotlarda İngilizce karşılık varsa kullanılabilir (ör. `.to_string()` = `.metin()`).
- Lisanslı paketlerin takma adları yalnız o paketin KENDİ belgesindedir; kurulu değilse iletişim yönlendirmesi (§16).

Doğrulanmış örnek (yorumlayıcıda koşuldu, 2026-10-10) / Verified example:

```berk
use string
use istatistik
use math

function main() -> int do
    let name = "Berk"
    print("length: " + string::str_len(name).to_string())
    print("upper: " + string::str_upper(name))
    let data = [3, 5, 7]
    print("mean: " + istatistik::istats_mean(data).to_string())
    print("square: " + math::square(1.5).to_string())
    if string::str_len(name) == 4 then do
        print("ok")
    end
    return 0
end
```

Çıktı / Output: `length: 4` · `upper: BERK` · `mean: 5` · `square: 2.25` · `ok`

*EN — binding rules for international use: Berk is bilingual; the English keywords above compile identically to
the Turkish ones and may be mixed. Standard-library functions (core + public BPM packages) have **English
aliases** — thin wrappers that call the Turkish original with identical behaviour, parameter order and return
type. When the user writes in English, use English keywords and aliases. **Never guess an alias**: names are
often module-prefixed to avoid clashes (`string::str_len`, `istatistik::istats_mean`); take the exact name from
the library's training doc section "English aliases" (`egitim_oku <lib>`), otherwise use the Turkish original.
Aliases exist for functions only; struct, field and type-alias names stay as defined. Licensed packages document
their aliases only in their own package docs.*

---

## 3. Tipler

Yerleşik ilkel tipler (gerçek kodda görülen kanonik adlar):

| Tip | Anlam | Örnek değer |
|---|---|---|
| `sayı` | tamsayı (integer) | `42`, `-7`, `0` |
| `ondalık` | kayan nokta (float) | `3.14`, `0.0`, `-2.5` |
| `metin` | dizgi (string) | `"merhaba"` |
| `mantıksal` | boolean | `doğru`, `yanlış` |
| `bayt` | byte | `0..255` |
| `liste` | dinamik dizi | `[]`, `[1, 2, 3]` |
| `demet` | tuple | `(1, "a")` |

**Jenerikler köşeli parantezle `[ ]` yazılır** (süslü/açılı değil):

```berk
liste[bayt]            // byte listesi
liste[sayı]            // int listesi
Sonuç[liste[bayt], metin]   // Result<Vec<u8>, String>
Seçenek[sayı]          // Option<int>
```

---

## 4. Değişken ve sabit

```berk
değişken x = 10             // yeniden atanabilir
x = x + 1
değişken ad: metin = "Ali"  // tip açıkça verilebilir (opsiyonel)

sabit PI: ondalık = 3.14159
pub sabit HATA_YOK: sayı = 0    // dışa açık sabit
```

- Atama operatörü `=`.
- Tip çıkarımı vardır; tip açıkça yazılabilir: `değişken n: sayı = 0`.

---

## 5. Fonksiyonlar

```berk
// Temel: fonksiyon ad(param: tip, ...) -> dönüş_tipi yap ... son
fonksiyon topla(a: sayı, b: sayı) -> sayı yap
    döndür a + b
son

// Saf fonksiyon (yan etkisiz, sertifika-sınıfı için tercih edilir)
saf fonksiyon karesi(x: sayı) -> sayı yap
    döndür x * x
son

// Dışa açık + belgeli
/// TR: İki ondalığın büyüğü. EN: max of two floats. [REQ-MAT-001]
pub fonksiyon ondalık_maks(a: ondalık, b: ondalık) -> ondalık yap
    eğer a > b ise döndür a
    döndür b
son
```

- Dönüş tipi `->` ile verilir (kanonik). *Gerçek kodda ender olarak `döndür Tip yap` biçimi de görülür;
  yeni kod yazarken `-> Tip yap` kullan.*
- Parametre tipleri zorunludur; dönüş tipi olan fonksiyonlar `döndür` ile değer vermelidir.
- `saf` öneki = saf fonksiyon (I/O yok, global durum yok). `pub`/`açık` = dışa açık.
- `asenkron fonksiyon ad(...) -> Tip yap ... son` = eşzamansız fonksiyon.

---

## 6. Kontrol akışı

### if / else / else-if

```berk
eğer x > 0 ise yap
    yazdır("pozitif")
değilse eğer x == 0 ise yap     // ← else-if (değilse eğer VEYA veya eğer — ikisi de geçerli)
    yazdır("sıfır")
değilse yap
    yazdır("negatif")
son
```

Tek satır (blok gerekmez):

```berk
eğer m == "GET" ise döndür 0
```

İfade biçimi (üçlü / ternary) — `son` ile kapanır:

```berk
değişken seviye = eğer n <= 1 ise "Düşük" değilse "Yüksek" son
```

> ℹ️ **Koşul zinciri — ÜÇ biçim de geçerli (BERK v1.0.0'da test edildi, 12/12 PASS).**
> Parser (`[FIX-DANGLING-ELSE]`, `parser.rs:parse_else_clause`) aşağıdaki üç yazımın hepsini
> doğru çözer ve aynı sonucu üretir:
>
> 1. **`değilse eğer …` (aynı satır elif)** — en yaygın, stdlib'de bol:
>    ```berk
>    eğer n < 0 ise yap … değilse eğer n == 0 ise yap … değilse yap … son
>    ```
> 2. **`veya eğer …` (elif)** — eşdeğer else-if:
>    ```berk
>    eğer n < 0 ise yap … veya eğer n == 0 ise yap … değilse yap … son
>    ```
> 3. **Çok-satırlı `değilse` + iç `eğer` (else-blok)** — `değilse`'yi bir satırda bırakıp `eğer`'i
>    alt satıra yazarsan bu **elif değil**, ilk deyimi bir `eğer` olan normal `değilse` bloğudur
>    (kendi `son`'u ile kapanır); iç içe yazılır ama aynı davranışı verir.
>
> **Tek dikkat noktası:** else-if (kompakt) İSTİYORSAN `değilse eğer` / `veya eğer`'i **tek satırda**
> tut. `değilse`'yi tek başına bırakıp `eğer`'i alt satıra koyman hatalı değildir — sadece anlamı
> "else + iç if" olur (fazladan bir `son` gerektirir). Tercihin: kompakt zincir için tek-satır elif.

### while

```berk
değişken i = 0
iken i < 10 yap
    yazdır(i.metin())
    i = i + 1
son
```

### for-each

```berk
her biri eleman içinde liste yap
    yazdır(eleman.metin())
son

// aralık ile:
her biri i içinde aralık(0, 5) yap    // 0,1,2,3,4
    yazdır(i.metin())
son
```

`dur` = döngüden çık (break), `geç` = sonraki tura atla (continue).

### match (eşleştir)

```berk
eşleştir algoritma yap
    "gzip" => yap
        döndür gzip_sıkıştır(veri)
    son
    "lz4" => döndür lz4_sıkıştır(veri)   // tek ifadeli kol
    _ => döndür Hata("bilinmeyen")        // _ = varsayılan/joker
son
```

- Her kol `desen => gövde`. Gövde ya tek ifade ya `yap … son` bloğudur.
- `_` joker (varsayılan) koldur.

---

## 7. Yapılar (struct)

Yapı, **`tip Ad = yapı yap … son`** ile tanımlanır (bu Berk'e özgü — `yapı Ad` değil):

```berk
tip Kilit = yapı yap
    kilitli: mantıksal,
    sahip: sayı
son
```

Örnek oluşturma: **`Ad yap alan: değer, … son`**

```berk
fonksiyon kilit_yeni() -> Kilit yap
    döndür Kilit yap kilitli: yanlış, sahip: 0 - 1 son
son
```

Alan erişimi nokta ile: `k.kilitli`, `k.sahip`.

Yuvalı (nested) oluşturma tek satırda çoklu `son` ile kapanır:

```berk
döndür KilitSonuç yap başarılı: doğru, kilit: Kilit yap kilitli: doğru, sahip: iş_id son son
```

---

## 8. Modüller ve içe aktarma

```berk
// Dosyanın başında modül bildirimi (ad veya a::b hiyerarşisi):
modül web::router

// Başka modülü içe aktar:
kullan prelude

// Namespaced çağrı:
değişken m = prelude::sayı_min(3, 7)
```

- Bir dosya = bir modül. Modül adı `::` ile hiyerarşiktir (`modül web::router`).
- `kullan <modül>` ile içe aktar; sonra `modül::fonksiyon(...)` biçiminde çağır.
- **Çok segmentli yol tam yazılır** (2026-09-12'den beri): `sensor::filter::çevrim_m4(16)`,
  `embedded::bal::adc::max_deger(12)`. Kısa biçim (`filter::çevrim_m4`) de çalışır — modül
  hem tam yolu hem son segmentiyle kayıtlıdır.
- **Yol segmenti ayrılmış bir kelime olabilir**: `adc`, `spi`, `pwm`, `uart`, `i2c`, `timer`,
  `gpio`, `hal` yol/üye konumunda geçerli adlardır (bare değişken adı olarak değil).

**Ad çakışmasını nitelenmiş çağrı çözer.** İki modülde aynı fonksiyon adı varsa çıplak
çağrı ikisinden birine gider; tam yol doğru olanı seçer:

```berk
kullan embedded::bal::pwm
kullan embedded::bal::spi
// iki modülde de `gercek_frekans` var:
yazdır(metin(embedded::bal::pwm::gercek_frekans(72000000, 71, 999)))   // 1000 Hz
yazdır(metin(embedded::bal::spi::gercek_frekans(84000000, 3)))         // 5 250 000 Hz
```

---

## 9. Hata yönetimi — `Sonuç` ve `Seçenek` (yerleşik)

Dil çekirdeği şunları **yerleşik** sağlar:

- `Sonuç[T, E]` → `Tamam(değer)` (Ok) veya `Hata(e)` (Err)
- `Seçenek[T]` → `Bazı(değer)` (Some) veya `Hiçbir` (None; `None` da geçer — `Hiç`/`Yok` YAZMAYIN: desende her değerle eşleşen değişken olurdu, 2026-10-10'dan beri ayrıştırma hatası)
- `?` propagasyon operatörü, `.unwrap()`, `.unwrap_or(varsayılan)` metotları.

```berk
fonksiyon böl(a: sayı, b: sayı) -> Sonuç[sayı, metin] yap
    eğer b == 0 ise döndür Hata("sıfıra bölme")
    döndür Tamam(a / b)
son

fonksiyon kullan_böl() -> Sonuç[sayı, metin] yap
    değişken q = böl(10, 2)?        // ? = hata varsa erken döndür
    döndür Tamam(q + 1)
son
```

`dene` / `yakala` (try/catch) blok biçimi de mevcuttur; sertifika-sınıfı kod panik yerine
`Sonuç` döndürmeyi tercih eder ("panik yok — çağıran açıkça ele alır").

---

## 10. Değerler üzerinde yerleşik metotlar & fonksiyonlar

Gerçek kodda sık kullanılan (kanonik Türkçe adlarla):

| Çağrı | Anlam |
|---|---|
| `liste.uzunluk()` | eleman sayısı |
| `liste.ekle(x)` | sona ekle |
| `liste[i]` | indeksleme (0 tabanlı) |
| `[]` | boş liste literal'i |
| `metin.karakterler()` | karakter listesi |
| `metin.böl("/")` | ayırıcıya göre böl → liste |
| `sayı.metin()` / `deg.metin()` | metne çevir |
| `yazdır(x)` | ekrana yaz |
| `karakter_kodu(c)` | karakter → kod noktası (int) |
| `koddan_karakter(n)` | kod noktası → karakter |
| `aralık(a, b)` | [a, b) tamsayı listesi |
| `aralık_adım(a, b, adım)` | adımlı aralık |

---

## 11. Sertifika-sınıfı ek işaretler (opsiyonel ama yaygın)

Berk cert-grade koddan gelir; bu işaretleri koruyup taklit etmek idiomatiktir:

- `///` doküman yorumları + `[REQ-MODUL-NNN]` izlenebilirlik etiketleri.
- `@pre` / `@post` sözleşmeleri (doküman yorumu içinde).
- `saf` = saf fonksiyon (statik olarak I/O/global reddedilir).
- `etkiler(sabit_zaman)` / `effects(constant_time)` → derleyici yan-kanal (side-channel)
  denetleyicisi çalıştırır; gizli-veriye bağlı dallanma/indeksleme reddedilir.
- `kamu` / `public` yumuşak-anahtar parametre öneki (sabit-zaman fonksiyonlarında bir parametreyi
  "kamusal" ilan eder): `fonksiyon f(veri: liste[bayt], kamu n: sayı)`.

Yeni kod yazan YZ bunları **zorunlu görmemeli**, ama var olan stildeki dosyaları düzenlerken
korumalı ve yeni fonksiyonlar için `///` + `[REQ-…]` eklemeyi tercih etmelidir.

---

## 12. Sık yapılan hatalar (YZ'nin KAÇINMASI gerekenler)

1. **Süslü parantez `{ }` kullanma.** Bloklar `yap … son`. Bu #1 hatadır.
2. **Noktalı virgül `;` ile satır bitirme.** Gerekmez; satır sonu yeterli.
3. **else-if'te `değilse` ile `eğer`'i farklı satırlara bölme** → `değilse eğer …` (veya `veya eğer …`) TEK satırda yaz (bkz. §6 kutusu).
4. **`yapı Ad yap`** biçiminde struct tanımlama → doğrusu **`tip Ad = yapı yap … son`**.
5. **Jenerikte `<T>` / `<T, E>` yazma** → Berk köşeli parantez kullanır: `Sonuç[T, E]`, `liste[bayt]`.
6. **Anahtar kelimeyi BARE ad olarak kullanma** (`tip`, `sabit`, `liste`, `sayı`, `son`,
   `yap`, `boş`, `fn`, `end`, `new`… değişken/parametre/fonksiyon adı olamaz).
   *2026-09-12 notu:* bu artık **sessizce bozulmaz, NET hata verir** — değişken konumu da
   parametre konumu da aynı davranır (98 ad: 69 kullanılabilir + 29 net ret, 0 bozuk).
   **Ama yol/üye konumunda geçerlidirler**: `embedded::bal::adc::max_deger(…)`, `x.durum`.
   Kural üç katmanlıdır; ayrıntı: `docs/BERK_KEYWORDS.md` → "GÜNCELLEME — 2026-09-12".
7. **C-stili `for (i=0; i<n; i++)` yazma** → `her biri i içinde aralık(0, n) yap … son` veya `iken` döngüsü.
8. **`class` / kalıtım varsayma** → Berk'te sınıf yok; `tip … = yapı` + serbest fonksiyonlar kullan.
9. **Her `yap` için bir `son`** yaz; yuvalı yapılarda `son` sayısını dikkatle dengele.
10. **İngilizce anahtar kelimelerle üretme** → parser kabul etse de kanonik çıktı Türkçe olmalı.

---

## 13. Tam, doğrulanmış örnek programlar

### 13.1 Merhaba + fonksiyon + koşul

```berk
fonksiyon mutlak(x: sayı) -> sayı yap
    eğer x < 0 ise döndür 0 - x
    döndür x
son

fonksiyon ana() -> sayı yap
    yazdır("mutlak(-4) = " + mutlak(-4).metin())
    döndür 0
son
```

### 13.2 Yapı + liste + döngü

```berk
tip Nokta = yapı yap
    x: ondalık,
    y: ondalık
son

saf fonksiyon uzaklık_kare(p: Nokta) -> ondalık yap
    döndür p.x * p.x + p.y * p.y
son

fonksiyon ana() -> sayı yap
    değişken noktalar = []
    noktalar.ekle(Nokta yap x: 3.0, y: 4.0 son)
    noktalar.ekle(Nokta yap x: 1.0, y: 0.0 son)

    her biri p içinde noktalar yap
        yazdır(uzaklık_kare(p).metin())
    son
    döndür 0
son
```

### 13.3 Sonuç (Result) + match

```berk
fonksiyon güvenli_böl(a: sayı, b: sayı) -> Sonuç[sayı, metin] yap
    eğer b == 0 ise döndür Hata("sıfıra bölme")
    döndür Tamam(a / b)
son

fonksiyon açıkla(kod: metin) -> metin yap
    eşleştir kod yap
        "ok"   => döndür "başarılı"
        "err"  => döndür "hatalı"
        _      => döndür "bilinmeyen"
    son
son
```

---

## 14. Hızlı çeviri kartı (yaygın dillerden Berk'e)

| Kavram | C/Rust/Python | Berk |
|---|---|---|
| blok | `{ }` / girinti | `yap … son` |
| fonksiyon | `fn f(x: i32) -> i32 {}` | `fonksiyon f(x: sayı) -> sayı yap … son` |
| değişken | `let x = 1;` | `değişken x = 1` |
| sabit | `const X = 1;` | `sabit X: sayı = 1` |
| if/elif/else | `if/elif/else` | `eğer … ise yap / değilse eğer … ise yap / değilse yap … son` |
| while | `while c {}` | `iken c yap … son` |
| for | `for x in xs {}` | `her biri x içinde xs yap … son` |
| match | `match v {}` | `eşleştir v yap … son` |
| struct | `struct S { a: i32 }` | `tip S = yapı yap a: sayı son` |
| enum | `enum E {}` | `numaralama E yap … son` |
| Result/Option | `Result<T,E>` / `Option<T>` | `Sonuç[T, E]` / `Seçenek[T]` |
| return | `return x;` | `döndür x` |
| true/false | `true` / `false` | `doğru` / `yanlış` |
| and/or/not | `&&` / `\|\|` / `!` | `ve` / `veya` / `değil` |
| print | `println!` / `print` | `yazdır(...)` |

---

## 15. Berk Package Manager (BPM) — paket kullanımı

Berk paketleri **`bpm`** (Berk Package Manager) ile yönetilir. Resmî registry:
**`https://packages.berk-systems.com`**. Paketler ed25519 imzalıdır; `--strict` imzayı doğrular.

### Temel komutlar
| Komut | Ne yapar |
|---|---|
| `bpm search <sorgu>` | registry'de paket ara |
| `bpm install <ad> [--strict]` | paketi `berk_modules/`'a kur (`--strict` = imzayı doğrula) |
| `bpm install <ad> --registry <url/dizin>` | belirli registry'den kur (çevrimdışı: yerel dizin/`file://`) |
| `bpm new <ad> [--bin]` | yeni proje iskeleti (`berk.toml` + `src/`) |
| `bpm add <ad>` | `berk.toml`'a bağımlılık ekle |
| `bpm build` / `bpm run` | projeyi derle / çalıştır |
| `bpm publish --registry <url> --token <t> --key <hex>` | HTTP registry'ye imzalı yayınla |
| `bpm keygen --out <önek>` | ed25519 yayıncı anahtar çifti üret |
| `bpm mirror <dizin> --key <hex>` | çevrimdışı ayna + imzalı `index.json` üret |

### Kur → kullan akışı
```powershell
bpm install json --strict            # json paketini kurar (imza doğrulanır)
```
```berk
kullan json                          // koddan içe aktar
değişken v = json::ayrıştır(metin)   // paketin fonksiyonlarını kullan
```
Bağımlılıkları `berk.toml`'a da yazabilirsin: `[dependencies]  json = "1.0"`.

### Registry paket kataloğu (public)
Bir YZ, kullanıcı bir işi tarif ettiğinde **çekirdekte yoksa** uygun paketi önerip
`bpm install <ad>` + `kullan <ad>` ile kullanmalıdır. Mevcut public paketler (tema bazlı):

- **Alan/domain:** `ai` (yapay zeka/ML), `bio` (biyoenformatik), `finance` (finans), `ros` (ROS2 modeli), `rtos` (gerçek-zamanlı)
- **Veri formatları:** `json`, `xml`, `yaml`, `ini`, `csv`, `msgpack`, `protobuf`, `binproto`, `compression`
- **Metin/desen:** `regex`, `arama` (arama algoritmaları), `desen`
- **Matematik/sayısal:** `complex`, `linalg`, `polynomial`, `math_3d`, `sparse`, `optim`, `istatistik`, `stats`, `simd`, `exact` (büyük tamsayı)
- **Grafik/geometri:** `graphics`, `color`, `image`, `csg`, `mesh`, `marching_cubes`, `cad`, `cad3d`, `vision`, `grafik`
- **Fizik/mühendislik:** `physics`, `fizik2d`, `fem`, `control`, `material`, `units`
- **Kripto/güvenlik:** `crypto`, `crypto_saf`, `crypto_kopru`, `crypto_native`, `pqc` (post-kuantum: ML-KEM/ML-DSA)
- **Ağ/web/DB:** `http`, `network`, `web`, `database`, `sqlite`
- **Gömülü/endüstriyel:** `embedded`, `hal`, `serial`, `modbus`, `firmata`, `slip`, `sensor`
- **Sinyal işleme (DSP):** `spectral` (sivil: FFT/STFT/ISTFT, NTT, 5G-NR OFDM, CT/geri-projeksiyon, sinyal üretimi)
- **Sistem/araç:** `gui`, `terminal`, `logging`, `validation`, `config`, `yetenek`, `paralel`, `audio`, `wasm`, `graf`, `histogram`, `pencere`, `nedensellik`, `rules`, `analiz`, `repro`, `protocol`

> **Çekirdek (paket DEĞİL, her zaman gelir):** `math`, `liste`, `string`, `io`, `fmt`, `utf8`, `encoding`,
> `sys`, `time`, `iter`, `collections`, `result`, `prelude`, `testing`, veri yapıları (`sozluk`, `kume`,
> `kuyruk`, `yigin`…), eşzamanlılık (`thread`, `sync`, `atomic`…). Bunlar için `bpm install` gerekmez.
>
> **Sektör/savunma paketleri** (adas, avionics, medical, mils, railway, robotics, space, telecom, dds,
> radar, `spectral_plus` — tam spektral yığın: radar/sonar/elektronik-harp/DoA — ve `protocols` — endüstriyel/
> insansız platform veriyolları: CAN/CAN-FD, LIN, FlexRay, MAVLink) public registry'de **yoktur**; yalnızca
> yetkili/lisanslı/çevrimdışı dağıtımla verilir. Public `spectral` yalnızca **sivil DSP** alt-kümesidir
> (radar/sonar/EW içermez).
>
> **Asistan için:** kullanıcının işi bu paketlerden birine denk geliyorsa paketi **adıyla söyle**, ne işe
> yaradığını belirt ve **ek olarak** edinme için **https://berk-tech.com/iletisim.html** adresine yönlendir (kurulum tarifi:
> `BPM_KULLANIM_REHBERI.md` §7). Genel kayıtta olmadıkları için `bpm install <ad>` tek başına önerilmez.

### İmza & güven
Her paket `<ad>@<sürüm>:<checksum>` mesajı üzerinden ed25519 imzalıdır (yayıncı anahtarı
`pubkey.txt`). Sertifikasyon-kritik kurulumda **`--strict`** kullan: imzasız/doğrulanamayan paket reddedilir.

---

## 16. AI Eğitim Korpusu — Keşif & Tembel Yükleme (`egitim_listesi` / `egitim_oku`)

Berk kütüphaneleri için ayrıntılı **AI eğitim belgeleri** (her biri gerçek stdlib kaynağından
üretilmiş; imza örnekleri + yorumlayıcıda doğrulanmış çalışan örnekler) vardır. Toplam korpus ~670 KB
olduğundan **hepsini baştan bağlama YÜKLEME** — bu token israfıdır. Bunun yerine **keşif indeksinden
tembel yükle**: yalnızca o an çalıştığın kütüphanenin belgesini çek.

### 16.1 Keşif indeksi (`egitim_indeks.json`)

Paylaşılan tarayıcı (`gen_egitim_indeks.py`) kurulu paket köklerini + çekirdek eğitim klasörünü tarar
ve `egitim_indeks.json` üretir. **Aynı üretici hem bu VS Code uzantısında hem Berk Studio'da kullanılır**
(tek sözleşme). Şema (özet):

```
kütüphaneler: {
  "<lib>": { lisans: çekirdek|public|lisanslı, kök: "<taranan-kök>",
             dosyalar: [ { ad, yol, sha256, bayt } ] },     // yol = köke GÖRELİ
  "_çekirdek": { lisans: çekirdek, kök: "<stdlib/egitim VEYA stdlib_rehber>",
                 dosyalar: [...], kütüphane_belge: { "<lib>": "<TEMA_BELGE.md>" } }
}
çekirdek_kütüphane_belge: { "<lib>": "<TEMA_BELGE.md>" }   // üst-düzey kopya (hızlı arama)
eksik_lisanslı: [ "radar", "spectral_plus", ... ]          // adı bilinen ama KURULU OLMAYAN lisanslılar
iletişim: "https://berk-tech.com/iletisim.html"
```

Bir dosyayı okurken tam yol = **`<egitim_indeks.json'un dizini>` + `/` + `<girdi.kök>` + `/` + `<dosya.yol>`**.
`kök` alanı **indeks dosyasının dizinine GÖRELİdir** (taşınabilirlik: aynı indeks cloud/geliştirici/son-kullanıcı
makinesinde çalışır). `_çekirdek` için `kök` = derleyici dağıtımında `stdlib/egitim`, bu depoda `stdlib_rehber`;
`yol` yalın dosya adıdır.

### 16.2 İki araç (dosya-sözleşmesi; harici asistanlar bu adımları izler)

- **`egitim_listesi`** → `egitim_indeks.json`'u oku, `kütüphaneler` anahtarlarını **lisans etiketiyle**
  listele. İÇERİK yükleme; yalnız envanter.
- **`egitim_oku <lib> [dosya]`** → şu **çözümleme sırasını** uygula:
  1. `kütüphaneler[<lib>]` **varsa** (paket kurulu) → onun `dosyalar[].yol`'unu (kökle birleştirip) oku.
     İstersen `sha256`'yı doğrula (bütünlük).
  2. yoksa `çekirdek_kütüphane_belge[<lib>]` **varsa** → `_çekirdek.kök`/`<TEMA_BELGE.md>`'yi oku
     (tema-gruplu genel bakış; ör. `math` → `STDLIB_02_SAYISAL.md`).
  3. yoksa `<lib>` **`eksik_lisanslı`** içindeyse → belge YOK. Bu **lisanslı** bir pakettir; public
     registry'de yoktur. Doğru cevap: *"Bu kütüphane lisanslıdır; erişim için
     **https://berk-tech.com/iletisim.html**"* (public paket olsaydı `bpm install <lib> --strict` derdin).
  4. hiçbiri değilse → bilinmeyen; `bpm search <lib>` öner.

### 16.3 Öncelik & lisans sınırı (neden bu sıra)

- **Kurulu paketin kendi `egitim/` belgesi her zaman öndedir** (derin, paketle sürüm-atomik gider);
  tema-belgesi yalnız yedek genel-bakıştır. Örn. `spectral` paketi kuruluysa `egitim_oku spectral`
  paketin `EGITIM_09_SPEKTRAL_HPC.md`'sini verir; değilse `PAKET_09_DSP_SES.md` genel bakışına düşer.
- **Lisanslı savunma paketleri** (`radar`, `spectral_plus`, `mils`, `dds`, `adas`…) **hiçbir tema-belgesinde
  API olarak geçmez**; dolayısıyla kurulu değillerse her zaman doğru şekilde **iletişim/lisans yönlendirmesine**
  düşerler. Bu, dosya-sistemi gerçeğiyle sağlanır — ayrı "gizle" mantığı yok. (Public `spectral` yalnız sivil DSP;
  radar/EH/izleme içermez.) Asistan bu paketleri adıyla bilir ve önerebilir; edinme her zaman iletişim üzerindendir.

### 16.4 İndeksi (yeniden) üret & tazele

```powershell
# Bu depoda (çekirdek tema-belgeleri stdlib_rehber'de):
python <_publish>\gen_egitim_indeks.py --stdlib-egitim .\stdlib_rehber --out .\egitim_indeks.json
# Kurulu paketleri de taramak için: --kok <berk_modules yolu> ekle.
```

**BPM'e bağlanınca tazele:** `bpm install`/`mirror` sonrası indeksi yeniden üret → asistan yeni eklenen
paketlerden ve kabiliyet geliştirmelerinden anında haberdar olur. (Berk Studio aynı üreticiyi paket-yolu
değişince çağırır.)

**Otomatik tazeleme (VS Code eklentisi):** eklenti aktivasyonda ve `berk_modules/` her değiştiğinde
(bpm install/mirror) indeksi KENDİLİĞİNDEN yeniden üretir ve çalışma alanına yazar:
`.berk/egitim_indeks.json` (makine-okur) + `.berk/EGITIM_DURUM.md` (asistanın ilk-bakış envanteri —
kurulu paketler, çekirdek belgeler, kurulu olmayan lisanslılar + iletişim yönlendirmesi). Elle tazeleme:
`BERK: Eğitim / Paket İndeksini Tazele` komutu. Harici stdlib kökü `berk.stdlibPath` ayarı ya da
`BERK_STDLIB_PATH` ile bildirilir. (Berk Studio'da eşdeğer: `EgitimKatalogService` her araç çağrısında
canlı tarar; tasarımcı asistanlarının sistem istemine kurulu paket envanteri otomatik eklenir.)

### 16.5 Kurulabilir genel paketler — asistan PAKET FARKINDALIĞI (2026-10-10)

Kurulu paketlerin yanında asistan, BPM genel kaydında (packages.berk-systems.com) olup **henüz kurulu OLMAYAN**
paketleri de bilir. Kaynak: çekirdek eğitim kökündeki **`paket_katalogu.json`** (bu depoda
`stdlib_rehber/paket_katalogu.json`; ad · alan · eğitim belgesi · açıklama; sürüm yazılmaz; lisanslı paket İÇERMEZ).
Üretici `D:\proje_analiz\berk\_publish\paket_katalogu_uret.py`'dir; elle düzenlenmez.

- Eklenti indeksi tazelerken kurulu olmayanları ayırır: `.berk/egitim_indeks.json` → **`kurulabilir_paketler`** +
  **`paket_önerisi`**; `.berk/EGITIM_DURUM.md` → **KURULABİLİR GENEL PAKETLER** bölümü (ad — alan — açıklama — belge).
- **Asistan davranışı:** kullanıcının işi kurulu olmayan bir genel pakete denk geliyorsa paketi adıyla söyle, ne işe
  yaradığını bir cümleyle açıkla ve kurmayı öner (`bpm install <ad> --strict`; Berk Studio'da Araçlar → Paket
  Yöneticisi). Kurulmadan `kullan <paket>` içeren kod yazma. API'yi kurulumdan önce de ilgili PAKET_xx belgesinden
  okuyabilirsin. Lisanslı paketlerde kurulum önerme — iletişim yönlendirmesi (§16.3).
- **Kavramla eşleştirme:** ad + alan + açıklamada Türkçe-duyarlı ara (ör. "sonlu eleman" → `fem`, "seri port" →
  `serial`). `bpm search` yalnız paket ADINDA arar; kavram için katalog listesine bak.
- **Proje yönergesi:** VS Code'daki AI araçları `.berk/` dosyalarını kendiliğinden okumaz. `BERK: AI Asistan
  Yönergesini Projeye Ekle` komutu kullanıcının seçtiği `AGENTS.md` / `CLAUDE.md` / `.github/copilot-instructions.md`
  dosyalarına `.berk/EGITIM_DURUM.md`'yi işaret eden işaretli bir blok yazar (yeniden çalıştırınca yerinde güncellenir).
- Berk Studio eşleniği: `egitim_listesi` (KURULABİLİR bölümü), `egitim_oku` (KURULU DEĞİL uyarısı), `paket_ara`
  (kavramla arama), `bpm_ara`/`bpm_kur` (kodlama ekranı; kurulum onaylı).

## 17. Çalıştırma ve dağıtım — `çalıştır` / `paketle` / AOT sınırı (2026-09-15)

Berk programını **üç** biçimde teslim edebilirsin; hangisini önereceğin programın içeriğine bağlıdır:

| Komut | Ne üretir | Ne zaman |
|---|---|---|
| `berk çalıştır app.berk` (`berk run`) | Yorumlayıcıyla çalıştırır; stdlib `BERK_STDLIB_PATH` → `berk.exe\..\stdlib` → `.\stdlib` sırasıyla bulunur | Geliştirme, test, IDE "Çalıştır" |
| `berk paketle app.berk -o app.exe` (`berk package`) | **Tek dosya uygulama**: `berk.exe` kopyası + kuyruğa eklenmiş yük (program + geçişli `kullan` zincirindeki stdlib dosyaları). Kullanıcıda kurulum, stdlib yolu, ortam değişkeni GEREKMEZ. Paketli davranış = `berk çalıştır` davranışı (aynı yorumlayıcı). GUI (`gorsel`, `gui::sahne`) dâhil HER program paketlenir; pencere yerlidir (tiny-skia + minifb, WebView/Tauri yok) | Son kullanıcıya teslim, demo, GUI uygulaması |
| `berk app.berk --emit exe -o app.exe` (LLVM AOT) | Yerli makine kodu | Saf hesap programları (statik diziler, tamsayı/ondalık, yapı). Dinamik `liste`/`.ekle`/`.uzunluk()`/`.metin()`/`harita`/closure yok → bunları kullanan program için `paketle` öner. **`kullan` ARTIK BAĞLANIR — `--modul-bagla` ile** (bkz. §17.1; bayrak varsayılan kapalıdır) |

### 17.1 AOT'ta `kullan` ve deterministik matematik (2026-09-19 · ÖLÇÜLDÜ)

**Bu bölüm §17'deki eski "AOT `kullan` bağlamaz" cümlesinin yerini alır.** O cümle
2026-09-18'e kadar doğruydu; `--modul-bagla` bayrağıyla geçersiz kaldı.

```powershell
berk app.berk --emit exe -o app.exe --modul-bagla
```

Bayrak **bilerek varsayılan KAPALIDIR** (mevcut derlemeler etkilenmesin diye opt-in).
Açıkken `kullan` zinciri derlemeye katılır; erişilemeyen modül fonksiyonları elenir ve
kaç tanesinin elendiği `[bilgi]` satırıyla bildirilir (sessiz düşme yok).

**Aşkın matematik AOT'ta çalışır.** `exp`, `ln`/`log`, `log10`, `sin`, `cos`, `tan`, `üs`
libm'e DEĞİL, saf-BERK referanslara (`kf_*_ref`) yönlendirilir; libm'in bunları sürümler
ve platformlar arasında son bitte saptığı için. Kapı: `tests\berk\aot_llvm_kapi.ps1` ·
**11/11** — her biri AOT'ta yorumlayıcıyla KARAKTER KARAKTER aynı.

> **ÖNKOŞUL — bu uzantıyla `ai` GELMEZ.** Uzantının stdlib'i BİLEREK sadeleştirilmiştir
> (`stdlib_sadelestir.ps1`): BPM'de yayınlanan paketler ve sektör kütüphaneleri çıkarılır,
> yalnız çekirdek kalır. `ai::kesin_float` için önce **`bpm install ai --strict`** gerekir.
> Kullanıcıya aşkın matematik önerirken bu satırı ATLAMA — yoksa `kullan ai::kesin_float`
> "modül bulunamadı" ile düşer ve kullanıcı nedenini rehberden öğrenemez.

**ÜÇ KOŞUL — kullanıcıya AOT matematik önerirken üçünü de söyle** (yukarıdaki `bpm install ai`
önkoşulu sağlandıktan sonra)**:**
1. Dosyanın başında `kullan ai::kesin_float`.
2. Derlemede `--modul-bagla`.
3. **stdlib bulunabilmeli.** `ai::kesin_float` ÇALIŞMA DİZİNİNE göre aranır (`./stdlib`),
   sonra `BERK_HOME\stdlib`. Berk kökü dışında derliyorsan `BERK_HOME`u köke ayarla.

> **GÖLGELEME TUZAĞI (2026-09-19'da gerçekten yaşandı).** Arama sırası `./stdlib`i
> `BERK_HOME`dan ÖNCE koyar. Yerelde ESKİ bir stdlib kopyası varsa sessizce O kullanılır.
> Berk Studio stdlib'i vendor ettiği için o dizinden yapılan derlemeler altı hafta eski bir
> `ai/kesin_float.berk` alıyordu; tek belirti `UndefinedFunction("kf_ln_ref")` idi ve
> TAMAMEN YANLIŞ bir yeri işaret ediyordu. Böyle bir hatada önce **hangi dosyanın
> yüklendiğini** doğrula. (Studio kopyasını eşitlemek için: `derle.ps1 -Studio`.)

**`metin()` AOT'ta YOKTUR.** `"x=" + metin(s)` yorumlayıcıda çalışır, AOT'ta derlenmez —
üstelik son bit farkını gizler. AOT'a gidecek programda değeri doğrudan bas: `yazdır(s)`.

**SINIR — determinizm ≠ doğruluk.** Ölçülen şey AOT çıktısının yorumlayıcı çıktısıyla
bit-birebir aynı olmasıdır; "sonuç tam doğrudur" değildir. `üs(2.0, 3.0)` her iki motorda
da `7.999999999999998` verir, 8.0 değil (`exp(y·ln x)` zincirinin yuvarlama birikimi).
İkisini birbirine karıştırma.

**KAPSAM DIŞI:** `taban`/`tavan`/`yuvarla` ONDALIK argümanda AOT'ta hâlâ reddedilir
(tamsayı argümanda özdeşliktir). Bunu eksik olarak SÖYLE, çalışıyormuş gibi yazma.

### 17.2 Windows'ta AOT bağlama tuzağı — Git Bash `link` gölgelemesi (2026-10-05 · SAHADA GÖRÜLDÜ)

AOT (`--emit exe`) derlemesi `.o` nesnesini ürettikten sonra Windows'ta MSVC bağlayıcısını
(`link.exe`) çağırır. **Git Bash'ten derlenirse** GNU coreutils'in kendi `link` komutu PATH'te
`link.exe`'nin önüne geçer ve bağlama şu hatayla düşer:

```
link: extra operand '/ENTRY:main'
```

Kodda sorun yoktur. Çözüm: AOT derlemeyi **PowerShell veya cmd**'den koşturun (ya da
`link.exe`'nin tam yolunu PATH'te öne alın). Yorumlayıcı (`berk run`) ve `paketle` bu
tuzaktan etkilenmez — bağlayıcı kullanmazlar. *On Windows, AOT linking calls MSVC `link.exe`;
under Git Bash, GNU coreutils' `link` shadows it and linking fails with `link: extra operand
'/ENTRY:main'`. The code is fine — run the AOT build from PowerShell or cmd. `berk run` and
`berk paketle` are unaffected.*

### 17.3 Paralellik — YALNIZ yorumlayıcı

Deterministik çok-çekirdek vardır ama **AOT'ta YOKTUR**. Ayrımı net söyle: deterministik
matematik AOT'ta derlenir, paralellik derlenmez.

> **ÖNKOŞUL:** `paralel` bir BPM paketidir (§15 · sistem/araç) ve uzantıyla GELMEZ —
> önce **`bpm install paralel --strict`**.

- Primitifler: `paralel_eşle(liste, fn)`, `paralel_filtrele(liste, yüklem)`,
  `paralel_indirge(liste, fn, başlangıç)`, `paralel_açık_mı()`. Bunlar yorumlayıcı
  YERLEŞİKLERİDİR (paket olmadan da vardır); `kullan paralel` ise adlandırılmış
  yardımcıları getirir (`p_kare`, `p_pozitif_mi`, `p_topla` …) ve paket gerektirir.
- **Sözleşme:** `paralel_eşle`/`filtrele` `--features parallel` ile rayon çok-çekirdek;
  feature KAPALIYKEN seri koşar ve sonuç **BİT-ÖZDEŞtir**. Paralellik yalnız hızlandırmadır.
- **`paralel_indirge` bilerek SERİDİR:** keyfi fonksiyon asosyatif olmayabilir (kayan-nokta
  birleşmezliği). Hızlanma HARİTA aşamasındadır, indirgemede değil. Bunu "eksik" diye
  sunma — bilinçli bir determinizm kararıdır.
- Geçilen fonksiyon **SAF** olmalıdır.
- AOT'ta paralel primitif çağrısı GEREKÇELİ reddedilir; paralel kod önerirken programın
  `berk run` için olduğunu baştan söyle.

`paketle` ayrıntıları:
- `--liste` yalnız yükü listeler (dosya yazmaz): `ana/<ad>.berk` + `stdlib/<göreli yol>` girdileri ve bayt boyutları.
- Paket yükü açılışta `%TEMP%\berk_paket\<fnv64>\` altına **bir kez** çıkarılır (`.tamam` işareti); içerik değişmedikçe yeniden çıkarılmaz.
- Paketli ikili alt komut almaz (`app.exe run …` yok); doğrudan gömülü `ana()`yı koşar, `ana()` dönüşü süreç çıkış kodudur.
- Bulunamayan `kullan` hedefleri `[!] bulunamadı:` uyarısıyla listelenir (yorumlayıcı da bunları atlar) — paketlemeden önce `berk kontrol` ile doğrula.
- Kabul kapısı: `tests\berk\paketle_olcut.ps1` (P1–P7); dil bulgusu B21 (`sabit K = 0 - 1` AOT katlama) `tests\berk\dil_bulgulari\dil_bulgulari_olcut.ps1`.

Örnek akış (GUI uygulaması):
```powershell
berk kontrol crm.berk                       # tip + saflık denetimi
berk çalıştır crm.berk                      # pencere açılır, geliştirme
berk paketle crm.berk -o BerkCRM.exe        # tek dosya teslim (≈ berk.exe + birkaç yüz KB)
```
#### Berk Studio Görsel Tasarımcı ▶ Çalıştır / 📦 Paketle (A5.1, 2026-09-15)
Görsel Tasarımcı'daki `.berkform` tasarımı derlenmez: tasarım → `gui::sahne` BERK programı (`%TEMP%\berk_studio_form\<ad>.berk`)
→ **Çalıştır** = `berk run` (ayrı yerli pencere, Escape kapatır) · **Paketle** = `berk paketle … --gui --ikili bin\berk_yorumlayici.exe`
(tek dosya, kurulumsuz exe ~20 MB). Görsel Tasarımcı asistanının araçları AYNI yolu kullanır: `form_calistir`, `form_paketle`
(`hedef` isteğe bağlı; varsayılan tasarım klasörü ya da `Belgeler\BerkProjects\<ad>\<ad>.exe`), `calisma_durumu` (son sonuç +
stdlib sağlığı). `form_durum` çıktısının sonunda `Çalıştırma:`/`Paket:` satırları vardır — "açıldı mı / exe nerede" sorularında oraya bak.
Sık hata: `Tanımsız fonksiyon: uyg_yeni` ya da `stdlib eksik … gui\sahne\uygulama.berk` → Studio stdlib'i eski; `derle.ps1 -Studio` eşitler.

YZ olarak kullanıcı "exe istiyorum / dağıtmak istiyorum" dediğinde **önce `paketle`** öner; `--emit exe`'yi yalnız yukarıdaki dar koşulda ve "LLVM özelliğiyle derlenmiş berk.exe gerekir" notuyla ver. Deterministik matematik gereken saf hesap programlarında `--emit exe --modul-bagla` artık geçerli bir yoldur (§17.1) — ama paralellik gerekiyorsa DEĞİL (§17.3).

---

*Bu rehber Berk derleyici kaynağı (`parser.rs`, `lexer.rs`), `docs/berk-syntax.md` ve gerçek derlenen
stdlib (`csv.berk`, `sync.berk`, `result.berk`, `compression.berk`, `web/router.berk`, `msgpack.berk`,
`prelude`…) çapraz doğrulanarak hazırlanmıştır. Sektör/Radar-spektral katmanlar kapsam dışıdır.*
