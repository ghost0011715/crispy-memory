# Berk Stdlib — YZ Asistanı Ana Rehberi / AI Assistant Master Guide

> **TR:** Bu belge, Berk çekirdek standart kütüphanesini (extension ile birlikte gelen
> `stdlib/` klasörü) bir YZ asistanının **doğru ve derlenebilir** biçimde kullanabilmesi için
> giriş noktasıdır. Söz dizimi temeli için önce [`BERK_AI_REHBERI.md`](BERK_AI_REHBERI.md),
> paket kurulumu için [`BPM_KULLANIM_REHBERI.md`](BPM_KULLANIM_REHBERI.md) okunmalıdır.
> Modül ayrıntıları 5 kategori belgesindedir (aşağıda §5).
>
> **EN:** This document is the entry point for an AI assistant to use the Berk **core**
> standard library (the `stdlib/` folder shipped with the extension) correctly. Read
> `BERK_AI_REHBERI.md` first for syntax; module details live in the 5 category docs (§5).
>
> **Doğrulama / Verification:** Tüm imzalar gerçek stdlib kaynağından alınmış; gövdesiz/
> `@native` bildirimler İKİ çalışma-zamanı katmanına karşı çapraz doğrulanmıştır
> (interpreter `eval_builtin` + `STDLIB_REGISTRY` FFI). / All signatures come from real
> stdlib sources, cross-checked against BOTH runtime layers.

---

## 1. İçe aktarma modeli / Import model

**TR:** Çekirdek modüller derleyiciyle birlikte gelir; `bpm install` GEREKMEZ. `kullan X`
yazıldığında çalıştırıcı `stdlib/X.berk` dosyasını yükler (arama sırası: `BERK_STDLIB` env →
çalıştırılabilir-göreli `../stdlib` → `./stdlib` → `.`). Yüklenen her fonksiyon **hem
nitelikli (`X::fonksiyon`) hem çıplak (`fonksiyon`)** adla kaydedilir.

**EN:** Core modules ship with the compiler; no `bpm install`. `kullan X` loads
`stdlib/X.berk`; every function is registered **both qualified (`X::fn`) and bare (`fn`)**.

```berk
kullan math
kullan liste

fonksiyon ana() -> sayı yap
    değişken açı = math::sin(1.5708)      // nitelikli — ÖNERİLEN / qualified — RECOMMENDED
    değişken aynı = sin(1.5708)           // çıplak ad da çalışır / bare name also works
    yazdır(açı.metin())
    döndür 0
son
```

**Kural / Rule:** Çakışmayı önlemek için **nitelikli biçimi tercih et** (`string::birleştir`
ile başka bir modülün `birleştir`'i çakışabilir). / Prefer the qualified form to avoid
name collisions.

- `yazdır(x)`, `aralık(a,b)`, `panik!`, `önkoşul` gibi bir avuç yerleşik **global**dir,
  `kullan` gerektirmez. / A handful of builtins are global and need no import.
- `kullan prelude` en sık kullanılanları tek seferde açar (result, option, string, io, fs
  re-export + yardımcılar). / `kullan prelude` opens the most-used set at once.

## 2. Çalışma zamanı iki katmandır / The runtime has two layers

**TR:** Gövdesiz veya `@native` bildirilen stdlib fonksiyonlarının gerçeklenmesi iki
katmandan birindedir: (1) yorumlayıcı yerleşikleri (`eval_builtin`, ~780 ad),
(2) `STDLIB_REGISTRY` FFI kaydı (~4190 anahtar). Gövdeli (saf Berk) fonksiyonlar doğrudan
çalışır. Kategori belgelerinde **"⚠ runtime yok"** işaretli az sayıda fonksiyon her iki
katmanda da karşılıksızdır — **bunları üretme**; işaretin yanındaki ✓ alternatifi kullan.

**EN:** Bodyless/`@native` stdlib functions are implemented in one of two layers
(interpreter builtins or the FFI registry). The few functions marked **"⚠ runtime yok"**
in the category docs exist in neither layer — **do not generate them**; use the listed
✓ alternative.

**Çağrı biçimi güvenliği / Call-form safety (interpreter.rs'ten doğrulandı):**

1. **GÖVDELİ** stdlib fonksiyonu her iki katmanı gölgeler → `mod::fn` de çıplak `fn` de güvenli.
2. **GÖVDESİZ + NİTELİKLİ** çağrı önce FFI registry'ye gider: anahtar REAL ise çalışır,
   **STUB ("not impl") ise HATA verir ve eval_builtin'e düşmez**; anahtar yoksa eval_builtin'e düşer.
3. **GÖVDESİZ + ÇIPLAK** çağrı önce eval_builtin'e gider → güvenli yol.
4. Diakritik katlama yok: `gzip_sıkıştır` ile registry'deki `gzip_sikistir` FARKLI adlardır.

Pratik kural / practical rule: **io ve fs'in gövdesiz fonksiyonlarını ÇIPLAK adla çağır**
(`read_to_string`, `exists`, `dosya_yaz` — repo testlerinin yaptığı gibi); `io::`/`fs::`
önekli biçim FFI stub'a düşebilir. `sys::`, `time::`, `http::`, `sqlite::`, `terminal::`,
`compression::` gövdesiz yüzeyleri FFI-REAL'dir → nitelikli biçim güvenlidir. `network` (33 fn),
`logging` (19 fn + `log`), `rules` (motor çekirdeği 40 fn) ve `regex` yakalama katmanının FFI
anahtarları STUB'dır → ilgili PAKET belgelerindeki ⚠ listelerine bak. / *Call bodiless io/fs
functions BARE; qualified sys/time/http/sqlite/terminal/compression are safe; network,
logging, rules-engine and regex-captures FFI keys are stubs — see the ⚠ lists.*

## 3. Değer semantiği ve closure yasağı / Value semantics & no closures

**TR — En kritik davranış kuralları (yorumlayıcı):**

1. **Değer semantiği:** listeler ve yapılar atamada/parametrede KOPYALANIR. Bir fonksiyon
   parametresi üzerinde yapılan yerinde değişiklik çağırana TAŞINMAZ (taşımak için `mut`
   parametre gerekir).
2. **`liste + [x]` DESTEKLENMEZ.** Birleştirme için `liste_birleştir(a, b)`.
3. **`.ekle(x)` metodu yalnız çıplak-değişken alıcıya geri yazar** (`xs.ekle(1)` çalışır;
   `yapı.alan.ekle(1)` güvenilir değildir). Yapı alanları için serbest fonksiyon ailesini
   kullan: `liste_ekle(m.köşeler, v)` gibi.
4. **Closure YOK.** Yüksek-mertebe fonksiyonlara (`liste_harita`, `liste_süz`,
   `liste_indirge`, `iter::*`) İSİMLİ, tanımlı bir `fonksiyon` geçilir; satır-içi lambda
   yazılamaz.
5. **Tuple dönüşü yok** → çok değerli sonuçlar küçük `yapı` tipleriyle döner
   (ör. `math::SinKos`).

**EN:** Lists/structs are copied on assignment and parameter passing (in-place edits do not
escape a function unless the parameter is `mut`); `liste + [x]` is unsupported; `.ekle()`
writes back only to a bare-variable receiver — use the free `liste_*` family for struct
fields; there are NO closures — pass a NAMED function to higher-order APIs; no tuples —
multi-value results use small structs.

```berk
kullan liste

fonksiyon iki_kat(x: herhangi) -> herhangi yap
    döndür x * 2
son

fonksiyon ana() -> sayı yap
    değişken sayılar = [1, 2, 3]
    değişken katlar = liste_harita(sayılar, iki_kat)   // isimli fonksiyon geçilir
    yazdır(liste_uzunluk(katlar).metin())
    döndür 0
son
```

## 4. Hata disiplini / Error discipline

**TR:** Sertifika-sınıfı stil: panik yerine `Sonuç[T, metin]` döndür; `?` ile yay;
`eşleştir` veya `.unwrap_or()` ile ele al. Metin→sayı çevrimi için ÇALIŞAN kanonik yol
**cast**tir: `"42" olarak sayı`, `"3.14" olarak ondalık` (hata durumunda çalışma-zamanı
hatası). `prelude::tam_ayrıştır` / `ondalık_ayrıştır` şu an runtime karşılıksızdır (⚠).

**EN:** Return `Sonuç[T, metin]` instead of panicking; propagate with `?`. For string→number
use the cast expression `"42" olarak sayı` — the prelude parse helpers currently have no
runtime backing.

**Kurucular / Constructors:** `Sonuç` → `Tamam(v)` / `Hata(e)`; `Seçenek` → `Bazı(v)` /
**`Hiçbir`** (`Yok` ve `None` da kabul edilir). **`Hiç` tek başına None DEĞİLDİR** — lexer
onu sıradan tanımlayıcı sayar; desen konumunda her şeyle eşleşir. Daima `Hiçbir` yaz. /
*The None constructor/pattern is `Hiçbir` — bare `Hiç` is just an identifier; never use it.*

## 5. Belge haritası / Document map

| Belge / Doc | Modüller / Modules | Fonksiyon / Fn |
|---|---|---|
| [`STDLIB_01_VERI_YAPILARI_METIN.md`](stdlib_rehber/STDLIB_01_VERI_YAPILARI_METIN.md) | liste, sozluk, kume, sirali, kuyruk, yigin, halka, oncelik, collections, iter, string, utf8 | ~171 |
| [`STDLIB_02_SAYISAL.md`](stdlib_rehber/STDLIB_02_SAYISAL.md) | math, matris, vektor, lineer, random, deterministic | ~194 |
| [`STDLIB_03_SISTEM_GC.md`](stdlib_rehber/STDLIB_03_SISTEM_GC.md) | io, fs, sys, encoding, fmt, time | ~376 |
| [`STDLIB_04_ESZAMANLILIK.md`](stdlib_rehber/STDLIB_04_ESZAMANLILIK.md) | async, async::stream, vaat, thread, sync, atomic, eszamanlilik | ~171 |
| [`STDLIB_05_HATA_TEST_PRELUDE.md`](stdlib_rehber/STDLIB_05_HATA_TEST_PRELUDE.md) | result, testing, prelude (+ saf.berk durum notu) | ~65 |

**Paket belgeleri / Package docs** (kurulum: `bpm install <ad> --strict` → `kullan <ad>`):

| Belge / Doc | Paketler / Packages |
|---|---|
| `stdlib_rehber/PAKET_01_VERI_FORMATLARI.md` | json, xml, yaml, ini, csv, msgpack, protobuf, binproto, compression, config |
| `stdlib_rehber/PAKET_02_METIN_DESEN.md` | regex, arama, desen |
| `stdlib_rehber/PAKET_03_MATEMATIK.md` | complex, linalg, polynomial, math_3d, sparse, optim, istatistik, stats, simd, exact, analiz (zeta) |
| `stdlib_rehber/PAKET_04_GRAFIK_GEOMETRI.md` | graphics, color, image, csg, mesh, marching_cubes, cad, cad3d, vision, grafik (kaplumbağa) |
| `stdlib_rehber/PAKET_05_FIZIK_MUH.md` | physics, fizik2d, fem, control, material, units |
| `stdlib_rehber/PAKET_06_KRIPTO.md` | crypto, crypto_saf, crypto_kopru, crypto_native, pqc (ML-KEM/ML-DSA) |
| `stdlib_rehber/PAKET_07_AG_WEB_DB.md` | http, network, web (58 modül), database, sqlite, logging |
| `stdlib_rehber/PAKET_08_GOMULU_RTOS.md` | serial, modbus, firmata, slip, embedded (bal + platforms), hal, sensor, rtos |
| `stdlib_rehber/PAKET_09_DSP_SES.md` | spectral (sivil DSP alt kümesi), audio |
| `stdlib_rehber/PAKET_10_SISTEM_ARAC_GUI.md` | terminal, gui, validation, yetenek, paralel, wasm, graf, histogram, pencere, nedensellik, rules, repro, protocol |
| `stdlib_rehber/PAKET_11_ALAN.md` | ai, bio, finance, ros |

**Kullanım önerisi (YZ için) / Usage advice (for AI):** Bir görevde hangi modülün
gerektiğine bu tablolardan karar ver, ilgili kategori belgesinin SADECE o modül bölümünü oku,
imzaları oradan birebir al. / Decide the module from these tables, read only that module's
section in the category doc, copy signatures verbatim.

## 6. Hızlı tuzak listesi / Quick pitfall list

1. Kanonik blok `yap … son`; `;` yok; jenerikler `[ ]`. (Ayrıştırıcı `{ }` bloğunu ve
   bildirimde `<T>`yi UYUMLULUK için tolere eder — `{ }` "kademeli emeklilik" uyarısı alır —
   ama ASLA üretme; açılı jenerikli KURUCU çağrısı `Bazı<sayı>(5)` zaten ayrıştırma hatasıdır.)
2. `değilse eğer` / `veya eğer` TEK satırda (else-if).
2a. `eşleştir` kolları satır satır yazılır; kol sonunda `,`/`;` OPSİYONEL ayraçtır
   (hata değildir) — kanonik yazım ayraçsızdır. Kurucu desenleri (`Tamam(v)`, `Hata(e)`,
   `Bazı(x)`, `Hiçbir`) ve literal/`_` desenleri desteklenir.
2b. **`async` modülü nitelikli çağrılamaz** — `async` anahtar kelimedir; `async::ready(...)`
   ayrıştırma hatası verir. `kullan async` sonrası ÇIPLAK ad kullan (`ready`, `poll`…).
2c. **if-İFADESİ üçlü (ternary) biçimdir ve `son` ile KAPANMAZ**:
   `eğer KOŞUL ise DEĞER1 değilse DEĞER2` — çağrı argümanı içinde de çalışır.
   Sonuna `son` eklemek çevreleyen bloğu kapatır ve "beklenmeyen 'son'" hatası üretir.
   / if-EXPRESSION is ternary and takes NO `son`; it works inside call arguments too.
2d. **Heterojen liste literalı tip hatasıdır** — `["Ali", 30]` gibi karışık tipli liste
   yazılamaz; `liste[metin]` bekleyen API'lere (ör. sqlite `*_param`) sayıları da metin yaz.
3. In-place liste fonksiyonları (`liste_ekle`, `liste_ata`, `liste_çıkar_son`) hedef olarak
   lvalue ister; sonucu ayrıca döndürürler.
4. `time::now()` ms cinsinden TAMSAYI döndürür; DateTime/Duration üst-API'sinin bir kısmı
   "⚠ runtime yok" — belge 03'e bak. / `time::now()` returns integer milliseconds.
5. `fmt` modülünün bir kısmı STUB'dır (sabit yer-tutucu döndürür) — belge 03'teki gerçek/stub
   ayrımına bak. / Part of `fmt` is stubbed; see doc 03.
6. Rastgelelik: `random` saf-Berk PRNG'dir (tohumlanabilir, deterministik); kripto için
   `crypto` paketi kurulur (`bpm install crypto --strict`).
7. Sözlük/küme gibi koleksiyonlarda anahtar tipleri ve API'ler belge 01'dekiyle sınırlıdır;
   Rust/Python API'si UYDURMA.
8. Bir fonksiyonun varlığından emin değilsen kategori belgesinde ara; yoksa "belgelenmedi"
   kabul et ve alternatif kur. / If a function is not in the docs, treat it as nonexistent.
9. **AOT (`--emit exe`) ile yorumlayıcı aynı stdlib'i GÖRMEZ.** (2026-09-19)
   - `kullan` AOT'ta yalnız `--modul-bagla` bayrağıyla bağlanır (varsayılan KAPALI).
   - `ai::kesin_float` aşkın fonksiyonları (`exp/ln/log/sin/cos/tan/üs`) AOT'ta ÇALIŞIR
     (kapı 11/11), ama `metin()` AOT'ta YOKTUR — `"x=" + metin(s)` derlenmez.
     **ÖNKOŞUL:** `ai` ve `paralel` BPM paketleridir; uzantının sade stdlib'inde YOKTUR
     (`stdlib_sadelestir.ps1` onları bilerek çıkarır) → `bpm install ai --strict`.
   - `paralel` modülü (`paralel_eşle/filtrele/indirge`) YALNIZ yorumlayıcıdadır; AOT
     gerekçeli reddeder. `paralel_indirge` bilerek SERİDİR (kayan-nokta birleşmezliği),
     hızlanma harita aşamasındadır.
10. **Stdlib GÖLGELENEBİLİR.** Modül çözümü `./stdlib`i (çalışma dizinine göreli)
   `BERK_HOME\stdlib`den ÖNCE dener. Yerelde eski bir kopya varsa sessizce o yüklenir ve
   belirti ilgisiz bir `UndefinedFunction` olur. Böyle bir hatada önce HANGİ DOSYANIN
   yüklendiğini doğrula — fonksiyonun kendisini aramadan önce.

## 7. Çekirdek + paket sınırı / Core vs package boundary

**TR:** Bu rehber ÇEKİRDEK stdlib'i kapsar. `json`, `xml`, `csv`, `regex`, `http`, `crypto`,
`linalg`, `graphics` … gibi işlevler PAKETTİR: `bpm install <ad> --strict` + `kullan <ad>`
(bkz. `BPM_KULLANIM_REHBERI.md`, katalog: `BERK_AI_REHBERI.md` §15). Paket kütüphanelerinin
eğitim belgeleri `stdlib_rehber/PAKET_*.md` dosyalarındadır.

**EN:** This guide covers the CORE stdlib. json/xml/http/crypto/… are packages: install via
`bpm install <name> --strict`, then `kullan <name>`. Package training docs live in
`stdlib_rehber/PAKET_*.md`.
