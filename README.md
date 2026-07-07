# Kompleksitas Algoritma & Desain Database
### Studi Kasus Nyata: E-Commerce, CQRS, Indexing, dan Batch Processing

---

## Tujuan Dokumen

Dokumen ini menyusun implementasi praktis untuk studi kasus e-commerce yang mencakup:
- desain skema database relasional 8 tabel,
- bulk insert data dummy dengan Python dan mysql-connector-python,
- query analitik dengan JOIN 8 tabel,
- indeks yang sesuai untuk MySQL 8,
- pola CQRS sederhana menggunakan tabel ringkasan `sales_summary`.

Seluruh kode yang digunakan tersedia di:
- [\.sql](.sql)
- [seeder.py](seeder.py)

---

## 1. Skema E-Commerce yang Digunakan

Sistem ini terdiri dari 8 tabel utama berikut:

| Tabel | Fungsi | Kunci Relasi |
| --- | --- | --- |
| categories | master kategori produk | - |
| warehouses | master gudang | - |
| products | master produk | `category_id`, `warehouse_id` |
| customers | data pelanggan | - |
| orders | transaksi pesanan | `customer_id` |
| order_items | detail item setiap order | `order_id`, `product_id` |
| payments | pembayaran order | `order_id` |
| shipments | pengiriman order | `order_id`, `warehouse_id` |

Skema ini mengikuti pola transaksi e-commerce yang umum: satu order memiliki banyak item, satu order memiliki satu atau lebih pembayaran, dan satu order bisa memiliki satu shipment.

---

## 2. Struktur Database

DDL lengkap tersedia di [\.sql](.sql). Secara ringkas, tabel-tabel utama dibuat dengan:
- `AUTO_INCREMENT` pada semua primary key,
- `FOREIGN KEY` dengan aturan `ON UPDATE CASCADE` dan `ON DELETE` yang sesuai,
- indeks pendukung untuk join dan filter,
- tabel `sales_summary` untuk pola CQRS sederhana.

Contoh struktur utama:

```sql
CREATE TABLE categories (
  category_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  PRIMARY KEY (category_id)
);

CREATE TABLE products (
  product_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_id INT UNSIGNED NOT NULL,
  warehouse_id INT UNSIGNED NOT NULL,
  name VARCHAR(150) NOT NULL,
  sku VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  PRIMARY KEY (product_id),
  FOREIGN KEY (category_id) REFERENCES categories(category_id),
  FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id)
);
```

---

## 3. Seeder Data Dummy dengan Python

Script seeder yang dibuat di [seeder.py](seeder.py) melakukan hal berikut:
- menghubungkan ke MySQL menggunakan `mysql-connector-python`,
- melakukan bulk insert dengan `executemany()`,
- memakai ukuran batch `10.000` baris,
- menghasilkan data dummy untuk seluruh tabel master dan transaksi,
- membuat 1 juta baris di `order_items` secara paralel memakai `concurrent.futures.ProcessPoolExecutor`.

Prinsip yang diterapkan:
- data master diisi terlebih dahulu,
- foreign key diisi dari ID yang valid dari tabel parent,
- proses bulk insert dipisah per batch agar lebih efisien,
- paralelism diterapkan hanya untuk tabel dengan volume data besar.

---

## 4. Query Analitik 8 Tabel

Query berikut menghitung total penjualan per customer, gudang, dan kategori, lalu mengelompokkan hasilnya:

```sql
EXPLAIN ANALYZE
SELECT
    c.full_name AS customer_name,
    w.name AS warehouse_name,
    cat.name AS category_name,
    SUM(oi.quantity * p.price) AS total_sales
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
JOIN categories cat ON cat.category_id = p.category_id
JOIN shipments s ON s.order_id = o.order_id
JOIN warehouses w ON w.warehouse_id = s.warehouse_id
JOIN payments pay ON pay.order_id = o.order_id
WHERE pay.status = 'paid'
  AND pay.created_at >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
GROUP BY
    c.full_name,
    w.name,
    cat.name
ORDER BY total_sales DESC;
```

`EXPLAIN ANALYZE` dipakai untuk melihat plan eksekusi dan mengidentifikasi bagian yang menjadi bottleneck.

---

## 5. Index yang Direkomendasikan

Untuk mempercepat query join dan filter, indeks berikut sangat membantu:

```sql
CREATE INDEX idx_orders_customer_id_created_at
ON orders (customer_id, created_at);

CREATE INDEX idx_order_items_order_id_product_id
ON order_items (order_id, product_id);

CREATE INDEX idx_products_product_id_category_id
ON products (product_id, category_id);

CREATE INDEX idx_shipments_order_id_warehouse_id
ON shipments (order_id, warehouse_id);

CREATE INDEX idx_payments_order_id_status_created_at
ON payments (order_id, status, created_at);
```

Use case utamanya adalah:
- join antar tabel transaksi,
- filtering berdasarkan rentang waktu,
- grouping agregat pada data besar.

---

## 6. Penerapan CQRS Sederhana

Untuk memisahkan beban baca laporan dari beban tulis transaksi, diterapkan pola CQRS sederhana dengan tabel `sales_summary`.

### Struktur tabel

```sql
CREATE TABLE sales_summary (
  summary_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  customer_name VARCHAR(150) NOT NULL,
  gudang_name VARCHAR(150) NOT NULL,
  kategori_name VARCHAR(100) NOT NULL,
  tanggal DATE NOT NULL,
  total_sales DECIMAL(14,2) NOT NULL DEFAULT 0.00,
  PRIMARY KEY (summary_id),
  UNIQUE KEY uk_sales_summary_unique (customer_name, gudang_name, kategori_name, tanggal)
);
```

### Proses sinkronisasi batch

Script Python di [seeder.py](seeder.py) memanggil query rekap harian berikut:

```sql
INSERT INTO sales_summary (customer_name, gudang_name, kategori_name, tanggal, total_sales)
SELECT
    c.full_name,
    w.name,
    cat.name,
    DATE(o.order_date),
    SUM(oi.quantity * p.price)
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
JOIN categories cat ON cat.category_id = p.category_id
JOIN shipments s ON s.order_id = o.order_id
JOIN warehouses w ON w.warehouse_id = s.warehouse_id
JOIN payments pay ON pay.order_id = o.order_id
WHERE pay.status = 'paid'
  AND DATE(o.order_date) = %s
GROUP BY c.full_name, w.name, cat.name, DATE(o.order_date)
ON DUPLICATE KEY UPDATE total_sales = VALUES(total_sales);
```

Dengan pola ini, dashboard/reporting bisa membaca dari `sales_summary` tanpa harus menghitung ulang dari 8 tabel transaksi setiap saat.

---

## 7. Query Baca Ringkas dari `sales_summary`

```sql
EXPLAIN ANALYZE
SELECT
    kategori_name,
    SUM(total_sales) AS total_penjualan_per_kategori
FROM sales_summary
GROUP BY kategori_name
ORDER BY total_penjualan_per_kategori DESC;
```

---

## 8. Kesimpulan

Implementasi ini menunjukkan bahwa performa sistem tidak hanya ditentukan oleh logika aplikasi, tetapi juga oleh:
- desain skema yang benar,
- penggunaan index yang tepat,
- strategi bulk insert untuk data besar,
- pemisahan beban baca dan tulis melalui CQRS.

Bila data terus bertambah, pola seperti ini akan jauh lebih scalable dibandingkan menjalankan query agregat berat langsung dari tabel transaksi setiap kali ada permintaan laporan.
)
SELECT n, (n % 5) + 1 FROM seq;
```

> Urutan INSERT mengikuti urutan FK (master data dulu, baru transaksi) supaya tidak kena error `foreign key constraint fails`.

**Langkah 3 — Jalankan query 8-join TANPA index tambahan**

```sql
EXPLAIN ANALYZE
SELECT c.name, w.name AS gudang, cat.name,
       SUM(oi.qty * oi.price) AS total
FROM orders o
JOIN customers c    ON c.id = o.customer_id
JOIN order_items oi  ON oi.order_id = o.id
JOIN products p      ON p.id = oi.product_id
JOIN categories cat  ON cat.id = p.category_id
JOIN payments pay    ON pay.order_id = o.id
JOIN shipments s     ON s.order_id = o.id
JOIN warehouses w    ON w.id = s.warehouse_id
WHERE o.created_at BETWEEN DATE_SUB(NOW(), INTERVAL 90 DAY) AND NOW()
GROUP BY c.name, w.name, cat.name;
```

Hasil `EXPLAIN ANALYZE` (format MySQL 8) yang tipikal muncul di 5.000 baris (kolom `created_at`, `customer_id`, `order_id`, `product_id`, `category_id`, `warehouse_id` belum di-index selain PK):

```
-> Table scan on order_items  (cost=... rows=5000) (actual time=... rows=5000 loops=1)
-> Filter: (o.created_at between ...)
   -> Table scan on orders  (cost=... rows=1500) (actual time=... rows=1500 loops=1)
-> Hash join ...
Execution time: ~11-15 ms
```

Di skala 5.000 baris angkanya masih kecil (belasan ms), **tapi perhatikan `Table scan`-nya** — optimizer terpaksa baca seluruh tabel `order_items` dan `orders` karena tidak ada index di `created_at` maupun kolom FK (index MySQL otomatis hanya dibuat untuk kolom `PRIMARY KEY` dan kolom yang dipakai `FOREIGN KEY` sebagai referensi, bukan kolom FK anak-nya sendiri jika tidak dideklarasikan eksplisit). Inilah pola yang, kalau dibiarkan sampai skala jutaan baris seperti di 2.1, berubah jadi 8-20 detik.

**Langkah 4 — Tambahkan index yang relevan**

```sql
CREATE INDEX idx_orders_created_at    ON orders(created_at);
CREATE INDEX idx_orders_customer_id   ON orders(customer_id);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);
CREATE INDEX idx_products_category_id   ON products(category_id);
CREATE INDEX idx_payments_order_id      ON payments(order_id);
CREATE INDEX idx_shipments_order_id     ON shipments(order_id);
CREATE INDEX idx_shipments_warehouse_id ON shipments(warehouse_id);

ANALYZE TABLE orders, order_items, products, payments, shipments; -- refresh statistik optimizer
```

**Langkah 5 — Jalankan ulang query yang sama, bandingkan plan**

```
-> Index range scan on orders using idx_orders_created_at (actual time=... rows=372 loops=1)
-> Index lookup on order_items using idx_order_items_order_id (actual time=... rows=4 loops=372)
-> Nested loop inner join ...
Execution time: ~3-5 ms
```

| Tahap             | Jenis Scan Dominan | Execution Time (5.000 baris) |
| ------------------ | ------------------- | ----------------------------- |
| Sebelum index      | Table scan (full scan) | ~11-15 ms                  |
| Setelah index      | Index range/lookup scan | ~3-5 ms                   |

> Di 5.000 baris, selisihnya "cuma" beberapa milidetik — gampang diabaikan saat dev/testing. Tapi karena kompleksitas *full table scan* tumbuh linear terhadap jumlah baris sementara *index scan* nyaris konstan (mirip pola O(n) vs O(log n) di tabel 1.1), begitu data bertambah ke jutaan baris (skala produksi di 2.1), selisih ini yang meledak jadi detik. **Inilah kenapa index harus dipasang sejak awal, bukan menunggu tabel membesar.**

**Cara verifikasi cepat tanpa index dulu vs sudah:**

```sql
-- Lihat index apa saja yang sudah terpakai optimizer untuk query di atas
EXPLAIN FORMAT=TREE <query di Langkah 3>;

-- Cek index yang sudah ada di tabel
SELECT table_name, index_name, column_name
FROM information_schema.statistics
WHERE table_schema = 'ecommerce'
  AND table_name IN ('orders','order_items','products','payments','shipments');
```

---

### 2.2.2 Skala Besar (Production-like): 1 Juta+ Baris

Untuk melihat efek `Table scan` vs `Index scan` yang jauh lebih nyata (detik, bukan milidetik), gunakan volume data yang lebih besar dan mendekati skala produksi:

| Tabel        | Jumlah Baris (Skala Besar) |
| ------------ | --------------------------- |
| categories   | 50                          |
| warehouses   | 20                          |
| products     | 5.000                       |
| customers    | 100.000                     |
| orders       | 300.000                     |
| order_items  | 1.000.000                   |
| payments     | 300.000                     |
| shipments    | 300.000                     |

`WITH RECURSIVE` dari 2.2.1 **tidak dipakai lagi di skala ini** karena dieksekusi baris-per-baris dan jadi sangat lambat begitu N mencapai ratusan ribu. Sebagai gantinya dipakai teknik **numbers table via CROSS JOIN** (set-based, jauh lebih cepat untuk bulk insert).

Skrip lengkapnya ada di [`scripts/mysql_large_sample_data.sql`](../scripts/mysql_large_sample_data.sql) — tinggal jalankan:

```bash
mysql -u root -p ecommerce < scripts/mysql_large_sample_data.sql
```

Isi skrip secara garis besar:

1. Buat tabel `numbers` berisi 1.000.000 baris angka via 3× cross join 10×10 (10×10×10×10×10×10 = 1.000.000) — jauh lebih cepat daripada CTE rekursif untuk N besar
2. Matikan `FOREIGN_KEY_CHECKS`, `UNIQUE_CHECKS`, dan `AUTOCOMMIT` sementara supaya bulk insert jutaan baris tidak lambat karena overhead validasi & commit per baris
3. Isi master data (`categories`, `warehouses`, `products`, `customers`) dari tabel `numbers`
4. Isi transaksi (`orders`, `order_items`, `payments`, `shipments`) dengan `n % <total_referensi>` supaya FK tetap valid meski di-generate massal
5. Nyalakan lagi `FOREIGN_KEY_CHECKS`/`UNIQUE_CHECKS`/`AUTOCOMMIT`, lalu `DROP TABLE numbers`
6. Query verifikasi jumlah baris per tabel di akhir skrip

**Alternatif: seeder pakai Go**

Selain skrip SQL murni, tersedia juga seeder [`cmd/seed/main.go`](../cmd/seed/main.go) yang melakukan hal yang sama dari sisi aplikasi (Go + `database/sql` + driver `go-sql-driver/mysql`): buat skema, lalu insert data dalam batch multi-row (`INSERT ... VALUES (...),(...),...`), dengan insert `order_items` (tabel terbesar) dipecah ke beberapa goroutine paralel (worker pool) agar lebih cepat.

```bash
go mod tidy
go run ./cmd/seed -orders=300000 -order-items=1000000 -customers=100000
```

Flag yang tersedia (semua opsional, default sudah sesuai skala di tabel atas):

| Flag             | Default   | Keterangan                                   |
| ---------------- | --------- | --------------------------------------------- |
| `-dsn`            | `root:@tcp(127.0.0.1:3306)/ecommerce?parseTime=true&multiStatements=true` | DSN MySQL, samakan dengan `.vscode/mcp.json` |
| `-categories`     | 50        | jumlah baris categories                       |
| `-warehouses`     | 20        | jumlah baris warehouses                       |
| `-products`       | 5000      | jumlah baris products                         |
| `-customers`      | 100000    | jumlah baris customers                        |
| `-orders`         | 300000    | jumlah baris orders (juga dipakai payments & shipments, 1:1) |
| `-order-items`    | 1000000   | jumlah baris order_items                      |
| `-batch-size`     | 1000      | jumlah baris per statement INSERT             |
| `-workers`        | 8         | jumlah goroutine paralel untuk insert order_items |

Untuk kembali ke skala tutorial 5.000 baris di 2.2.1, cukup jalankan dengan flag lebih kecil, misalnya:

```bash
go run ./cmd/seed -categories=10 -warehouses=5 -products=200 -customers=500 -orders=1500 -order-items=5000 -workers=2
```

**Perbandingan hasil yang diharapkan di skala ini (order_items 1 juta baris):**

| Tahap          | Jenis Scan Dominan       | Execution Time (perkiraan) |
| -------------- | ------------------------- | ---------------------------- |
| Sebelum index  | Table scan (full scan)    | ~2-5 detik                   |
| Setelah index  | Index range/lookup scan   | ~50-150 ms                   |

Jalankan `EXPLAIN ANALYZE` dari Langkah 3 & 5 di 2.2.1 dengan data hasil skrip ini — perbedaan `Table scan` vs `Index scan` akan jauh lebih terasa dibanding versi 5.000 baris, dan lebih mendekati kondisi nyata di 2.1 (8,5-20 detik pada 42 juta baris).

> **Catatan:** menjalankan skrip ini butuh waktu (insert 1 juta baris + generate `numbers` table) dan memori/disk lebih besar dari versi 5.000 baris. Jalankan di database development/tutorial, bukan database produksi.

---

### 2.3 Solusi: CQRS — Pisahkan Model Baca & Tulis

**Command Query Responsibility Segregation**: transaksi tetap normal (write), laporan pakai data yang sudah didenormalisasi (read).

**COMMAND SIDE (Write)**
- 8 tabel ternormalisasi (3NF): `orders`, `order_items`, `payments`, `shipments`, dst.
- Optimal untuk insert/update transaksi
- Konsisten & bebas anomali data
- Beban ringan karena hanya proses transaksi

**⇄ Event/CDC Sync Async**

**QUERY SIDE (Read)**
- Materialized view / read-replica / tabel ringkasan yang sudah didenormalisasi:
```
sales_summary(customer, gudang, kategori, tanggal, total)
```
- Sudah di-agregasi (SUM per hari) — tidak perlu JOIN 8 tabel saat dibaca
- Refresh berkala (mis. tiap 5-15 menit) atau via event streaming
- Query dashboard turun dari 8,5 detik menjadi puluhan milidetik

---

### 2.4 Best Practice Indexing Database

**❌ DON'T**
- Index di semua kolom "jaga-jaga" — memperlambat write & boros storage
- Index kolom dengan cardinality rendah sendirian (mis. status boolean)
- Urutan kolom composite index asal-asalan, tidak sesuai pola query
- Pakai `SELECT *` lalu filter di aplikasi, bukan di `WHERE` query

**✅ DO**
- Index kolom yang sering dipakai di `WHERE`, `JOIN`, dan `ORDER BY`
- Composite index: urutan kolom ikuti pola query paling sering (equality dulu, baru range)
- Covering index agar query cukup dibaca dari index, tanpa akses tabel
- Pantau query plan (`EXPLAIN ANALYZE`) & index yang tidak terpakai, lalu bersihkan

**Extension berguna — `pg_trgm` (PostgreSQL):**
- Mengubah `LIKE`/`ILIKE '%keyword%'` agar bisa memakai index (GIN/GiST), bukan full table scan
- Mendukung fuzzy/similarity search untuk toleransi typo
- Cocok untuk fitur autocomplete/search suggestion
- Trade-off: index GIN lebih besar & sedikit lebih lambat saat write dibanding B-tree biasa

---

### 2.5 Dampak Nyata: CQRS + Indexing pada Query Laporan

| Metrik                   | Sebelum           | Sesudah      |
| ------------------------ | ----------------- | ------------ |
| Waktu Query Dashboard    | 8,5 detik         | 45 ms        |
| Strategi Akses Data      | Full Table Scan   | Index Seek   |
| Isolasi Beban Baca/Tulis | Beban di DB Utama | Read Replica |

**Waktu eksekusi query (ms) berdasarkan jumlah baris data:**

| Jumlah Baris | Tanpa Index (JOIN 8 tabel) | Dengan Index + CQRS |
| ------------ | -------------------------- | ------------------- |
| 100 ribu     | 320 ms                     | 8 ms                |
| 1 juta       | 2.100 ms                   | 15 ms               |
| 10 juta      | 6.800 ms                   | 28 ms               |
| 42 juta      | 8.500 ms                   | 45 ms               |

---

## BAGIAN 03 — Back-of-the-Envelope Estimation

*Teknik estimasi cepat untuk memperkirakan kapasitas & performa sistem — bekal wajib technical interview (ref: [ByteByteGo](https://bytebytego.com/courses/system-design-interview/back-of-the-envelope-estimation))*

### 3.1 Apa itu Back-of-the-Envelope Estimation?

Estimasi cepat dan kasar untuk menguji apakah sebuah desain sistem masuk akal — sebelum dibangun.

> Istilah ini dipopulerkan oleh Jeff Dean (Google Senior Fellow): menggabungkan eksperimen pemikiran sederhana dengan angka-angka performa umum untuk melihat desain mana yang paling masuk akal, tanpa perlu membangun sistem nyata terlebih dahulu.

**3 fondasi yang wajib dikuasai:**
1. **Power of Two** — satuan volume data (KB, MB, GB, TB, PB)
2. **Angka Latency** — kecepatan relatif operasi memori, disk, jaringan
3. **Angka Availability** — makna di balik "99.9%" hingga "99.999%" uptime

**Kapan dipakai?**
- Menaksir kebutuhan server, storage, bandwidth sejak awal desain
- Membandingkan beberapa opsi arsitektur secara cepat
- Menjawab pertanyaan "apakah desain ini realistis untuk skala X?"
- Standar pertanyaan di technical/system design interview

---

### 3.2 Fondasi 1: Power of Two (Satuan Data)

| Pangkat | Nilai Perkiraan | Nama Lengkap | Singkatan |
| ------- | --------------- | ------------ | --------- |
| 2^10    | ~1 Ribu         | Kilobyte     | 1 KB      |
| 2^20    | ~1 Juta         | Megabyte     | 1 MB      |
| 2^30    | ~1 Miliar       | Gigabyte     | 1 GB      |
| 2^40    | ~1 Triliun      | Terabyte     | 1 TB      |
| 2^50    | ~1 Kuadriliun   | Petabyte     | 1 PB      |

**Contoh praktis:**
```
1 juta baris data user, tiap baris ±1 KB
= 1.000.000 x 1 KB
= ~1 GB (2^30 bytes)
```

> **Tips:** saat interview/perhitungan cepat, bulatkan angka. `99987 / 9.1` cukup didekati menjadi `100.000 / 10` — presisi bukan tujuan utama.

---

### 3.3 Fondasi 2: Angka Latency yang Wajib Diketahui

*Referensi klasik Jeff Dean (Google) — angka pasti berubah seiring hardware baru, tapi rasio kecepatannya tetap relevan.*

| Operasi                  | Perkiraan Waktu |
| ------------------------ | --------------- |
| L1 cache reference       | 0.5 ns          |
| L2 cache reference       | 7 ns            |
| Mutex lock/unlock        | 100 ns          |
| Baca 1 MB dari memori    | 250 µs          |
| Round trip 1 data center | 500 µs          |
| Disk seek                | 10 ms           |
| Baca 1 MB dari jaringan  | 10 ms           |
| Baca 1 MB dari disk      | 30 ms           |
| Round trip antar benua   | 150 ms          |

*(ns = nanodetik, µs = mikrodetik, ms = milidetik → 1 ms = 1.000 µs = 1.000.000 ns)*

**Kesimpulan praktis:**
- Memori sangat cepat, disk jauh lebih lambat — hindari disk seek bila bisa
- Kompresi data ringan itu cepat — kompres sebelum kirim lewat jaringan
- Data center berbeda lokasi = ada biaya waktu kirim data antar region
- Round trip dalam 1 data center jauh lebih murah daripada antar benua

---

### 3.4 Fondasi 3: Angka Availability ("Nines")

Semakin banyak angka 9, semakin sedikit downtime yang ditoleransi — dasar penentuan SLA.

| Availability | Downtime / Hari | Downtime / Minggu | Downtime / Tahun |
| ------------ | --------------- | ----------------- | ---------------- |
| 99%          | 14,4 menit      | 1,68 jam          | 3,65 hari        |
| 99,99%       | 8,64 detik      | 4,38 menit        | 52,6 menit       |
| 99,999%      | 864 ms          | 26,3 detik        | 5,26 menit       |
| 99,9999%     | 86,4 ms         | 2,63 detik        | 31,56 detik      |

> Service Level Agreement (SLA) dari penyedia cloud besar umumnya dipatok di 99.9% ke atas. Kenaikan dari 99% ke 99.99% terdengar kecil di atas kertas, tapi bedanya adalah 3,65 hari downtime per tahun vs kurang dari 1 jam — perbedaan yang sangat signifikan untuk bisnis kritikal.

---

### 3.5 Praktik: Estimasi QPS & Storage ala Twitter

*Contoh latihan sederhana — angka ilustratif, bukan data resmi Twitter.*

**1. Asumsi awal:**
- 300 juta pengguna aktif bulanan
- 50% aktif harian → 150 juta DAU
- Rata-rata 2 tweet/hari per user
- 10% tweet berisi media
- Data disimpan selama 5 tahun

**2. Hitung QPS:**
```
DAU = 300jt x 50% = 150 juta

QPS = 150jt x 2 tweet / 24 jam / 3600 detik
    ≈ 3.500 tweet/detik

Peak QPS = 2 x QPS ≈ 7.000 tweet/detik
```

**3. Hitung storage media (5 tahun):**

Asumsi ukuran rata-rata: tweet_id 64 byte, teks 140 byte, 1 media ≈ 1 MB

```
Storage media / hari = 150 juta x 2 tweet x 10% x 1 MB = 30 TB/hari
Storage media 5 tahun = 30 TB x 365 hari x 5 tahun ≈ 55 PB
```

---

### 3.6 Tips Praktis Saat Melakukan Estimasi

*Yang dinilai adalah cara berpikir, bukan ketepatan angka hingga desimal.*

1. **Bulatkan Angka** — `99987 / 9.1` cukup didekati `100.000 / 10`, hindari hitungan rumit yang buang waktu
2. **Tulis Semua Asumsi** — catat setiap asumsi (jumlah user, rasio aktif, dll) agar bisa dirujuk ulang saat pembahasan
3. **Beri Label Satuan** — tulis "5 MB", bukan cuma "5", hindari ambiguitas KB/MB/GB di tengah perhitungan
4. **Kuasai Topik Umum** — QPS, peak QPS, storage, cache, jumlah server adalah yang paling sering ditanyakan

---

## Key Takeaways

1. **Kompleksitas bukan teori kelas kuliah** — nested loop 4 tingkat pada filter produk nyata bisa jadi O(n⁴) dan meledak di production
2. **Batasi & ukur concurrency** — paralel mempercepat proses, tapi tanpa batas & locking yang tepat justru membuat sistem tidak stabil
3. **CQRS memisahkan tanggung jawab** — beban baca (laporan) dan tulis (transaksi) dipisah agar keduanya tetap cepat & stabil
4. **Index yang tepat, bukan index yang banyak** — rancang index berdasarkan pola query nyata, bukan asal ditambahkan ke semua kolom
5. **Estimasi dulu sebelum membangun** — power of two, angka latency, dan availability membantu menilai desain sejak di atas kertas
6. **Proses lebih penting dari presisi** — bulatkan angka, tulis asumsi, dan beri label satuan, itu yang dinilai saat estimasi cepat

---

*Berpikir kompleksitas & desain data sejak awal — bukan setelah production down.*