# ============================================================
# APLIKASI PEMANTAUAN TUMPAHAN MINYAK — PULAU SEMAU, NTT
# Area: Diperkecil — Sekitar KM Kuala Emas
# Metode: Menggunakan ASFSearchOptions (aman & tahan-versi)
# ============================================================

import os
import re
import zipfile
import traceback
from datetime import datetime, timezone

import asf_search as asf
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import xy as pixel_ke_koordinat
from rasterio.warp import transform as reproyeksi_koordinat
import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Pemantauan Tumpahan Minyak — Pulau Semau", layout="wide")

# ---------------------------
# KONFIGURASI — AREA SUDAH DIPERKECIL
# ---------------------------
# Batas presisi di sekitar titik kejadian KM Kuala Emas
BBOX = [123.50, -10.22, 123.60, -10.14]  # [minLon, minLat, maxLon, maxLat]
# asf_search menerima geometri sebagai WKT polygon, bukan bbox mentah
WKT_AREA = (
    f"POLYGON(("
    f"{BBOX[0]} {BBOX[1]}, {BBOX[2]} {BBOX[1]}, "
    f"{BBOX[2]} {BBOX[3]}, {BBOX[0]} {BBOX[3]}, "
    f"{BBOX[0]} {BBOX[1]}))"
)

TANGGAL_MULAI = "2026-07-29T00:00:00Z"
TANGGAL_AKHIR = "2026-08-31T23:59:59Z"

AMBANG_BATAS_DETEKSI = -18
LOKASI_SIMPAN_DATA = "./data/"
RIWAYAT_CSV = os.path.join(LOKASI_SIMPAN_DATA, "riwayat_analisis.csv")

# Titik acuan Pulau Semau / lokasi kejadian (KM Kuala Emas) — dipakai sebagai
# referensi jarak untuk merekomendasikan titik sampling terdekat ke pulau.
# Sesuaikan nilai ini kalau Anda punya koordinat garis pantai yang lebih presisi.
TITIK_ACUAN_SEMAU_LAT = -10.18
TITIK_ACUAN_SEMAU_LON = 123.55

# Titik tengah area kejadian, dipakai untuk mengambil data angin historis
CENTROID_LON = (BBOX[0] + BBOX[2]) / 2
CENTROID_LAT = (BBOX[1] + BBOX[3]) / 2

# Rentang kecepatan angin (m/s) di mana deteksi tumpahan minyak dari SAR dianggap
# valid secara operasional (referensi umum: NOAA / EU Copernicus EMSA CleanSeaNet)
AMBANG_ANGIN_MIN_MS = 3.0
AMBANG_ANGIN_MAKS_MS = 10.0

# ---------------------------
# JUDUL & INFORMASI
# ---------------------------
st.title("🛰️ Pemantauan Tumpahan Minyak — Pulau Semau, NTT")
st.subheader("Periode: 29 Juli – 31 Agustus 2026")

st.info("""
📍 Lokasi: Perairan Pulau Semau, Kab. Kupang, NTT
🔑 Titik kejadian: 10.18° LS, 123.55° BT (sekitar KM Kuala Emas)
📏 Area pencarian: ±90 km² (sudah diperkecil)
🛰️ Sumber data: Sentinel-1 (SAR) — ASF DAAC NASA
""")

# ---------------------------
# SIDEBAR — LOGIN NASA EARTHDATA (WAJIB UNTUK UNDUH DATA)
# ---------------------------
st.sidebar.header("🔐 Akun NASA Earthdata")
st.sidebar.caption(
    "Diperlukan hanya untuk MENGUNDUH citra. Daftar gratis di "
    "https://urs.earthdata.nasa.gov/"
)
earthdata_user = st.sidebar.text_input("Username Earthdata")
earthdata_pass = st.sidebar.text_input("Password Earthdata", type="password")

if "earthdata_session" not in st.session_state:
    st.session_state.earthdata_session = None
if "earthdata_login_ok" not in st.session_state:
    st.session_state.earthdata_login_ok = False


def _ekstrak_link_approve(pesan_error: str):
    """Ambil URL 'approve_app' dari pesan error 401 ASF, kalau ada."""
    import re
    m = re.search(r"https://urs\.earthdata\.nasa\.gov/approve_app\?[^\s\"'<]+", pesan_error)
    return m.group(0) if m else None


def login_earthdata():
    """Coba login ke NASA Earthdata dan simpan sesi di session_state."""
    if not earthdata_user or not earthdata_pass:
        st.sidebar.warning("Isi username dan password terlebih dahulu.")
        return

    with st.sidebar.status("Mencoba login ke NASA Earthdata...", expanded=False):
        try:
            sesi = asf.ASFSession().auth_with_creds(earthdata_user, earthdata_pass)
            st.session_state.earthdata_session = sesi
            st.session_state.earthdata_login_ok = True
        except Exception as e:
            st.session_state.earthdata_session = None
            st.session_state.earthdata_login_ok = False
            pesan = str(e)
            link_approve = _ekstrak_link_approve(pesan)

            if "401" in pesan or "Unauthorized" in pesan:
                st.sidebar.error("❌ Login gagal: kredensial salah atau aplikasi belum diotorisasi.")
            else:
                st.sidebar.error(f"❌ Login gagal: {pesan}")

            if link_approve:
                st.sidebar.warning(
                    "Akun Earthdata Anda belum memberi izin ke aplikasi ASF Search. "
                    "Ini wajib dilakukan **satu kali** lewat browser:"
                )
                st.sidebar.link_button("🔗 Beri Izin (Authorize) di NASA Earthdata", link_approve)
                st.sidebar.caption(
                    "Setelah klik link di atas dan menekan tombol Authorize di halaman NASA, "
                    "kembali ke sini dan klik 'Login Earthdata' lagi."
                )


if st.sidebar.button("🔑 Login Earthdata", type="primary"):
    login_earthdata()

if st.session_state.earthdata_login_ok:
    st.sidebar.success(f"✅ Berhasil login sebagai **{earthdata_user}**")


def buat_sesi_earthdata():
    """Kembalikan sesi Earthdata yang sudah login, atau None kalau belum."""
    return st.session_state.earthdata_session


# ---------------------------
# FUNGSI CARI DATA — MENGGUNAKAN ASFSearchOptions ✅
# ---------------------------
def cari_data_sentinel1():
    """Mencari citra Sentinel-1 GRD pada area & rentang tanggal yang ditentukan."""
    opts = asf.ASFSearchOptions(
        platform=asf.PLATFORM.SENTINEL1,
        processingLevel=asf.PRODUCT_TYPE.GRD_HD,
        beamMode=asf.BEAMMODE.IW,
        polarization=asf.POLARIZATION.VV_VH,
        start=TANGGAL_MULAI,
        end=TANGGAL_AKHIR,
        intersectsWith=WKT_AREA,
        maxResults=100,
    )

    hasil = asf.search(opts=opts)

    daftar_hasil = []
    for citra in hasil:
        props = citra.properties
        waktu_mulai = props.get("startTime", "") or ""
        daftar_hasil.append({
            "Tanggal Rekam": waktu_mulai[:10],
            "Jam Rekam": waktu_mulai[11:16],
            "Produk": props.get("processingLevel", ""),
            "Polarisasi": props.get("polarization", ""),
            "Tautan Unduh": props.get("url", ""),
        })
    return daftar_hasil


# ---------------------------
# FUNGSI UNDUH CITRA
# ---------------------------
def unduh_citra(tautan, sesi):
    if sesi is None:
        raise ValueError(
            "Belum login ke NASA Earthdata. Isi username & password di sidebar, "
            "lalu klik tombol '🔑 Login Earthdata' terlebih dahulu."
        )
    os.makedirs(LOKASI_SIMPAN_DATA, exist_ok=True)
    asf.download_url(url=tautan, path=LOKASI_SIMPAN_DATA, session=sesi)
    nama_berkas = os.path.join(LOKASI_SIMPAN_DATA, tautan.split("/")[-1])
    return nama_berkas


# ---------------------------
# FUNGSI CARI TIFF DI DALAM ZIP
# ---------------------------
def cari_band_pengukuran(jalur_zip):
    """
    Produk Sentinel-1 GRD dari ASF berbentuk .zip berisi file .tiff pengukuran
    di dalam folder measurement/. Fungsi ini mencari path GDAL virtual (/vsizip/)
    ke file tiff pertama yang ditemukan supaya bisa langsung dibuka rasterio.
    """
    if not jalur_zip.lower().endswith(".zip"):
        return jalur_zip  # sudah berupa GeoTIFF biasa

    with zipfile.ZipFile(jalur_zip, "r") as z:
        kandidat = [
            n for n in z.namelist()
            if "measurement" in n.lower() and n.lower().endswith(".tiff")
        ]
        if not kandidat:
            raise FileNotFoundError(
                "Tidak ditemukan file .tiff di dalam folder measurement/ pada arsip zip ini."
            )
        return f"/vsizip/{jalur_zip}/{kandidat[0]}"


# ---------------------------
# FUNGSI DETEKSI TUMPAHAN
# ---------------------------
def deteksi_tumpahan(jalur_citra, ambang_batas=AMBANG_BATAS_DETEKSI, maks_dimensi=3000):
    """
    Mendeteksi area tumpahan dari citra SAR.

    Citra Sentinel-1 GRD resolusi penuh bisa berukuran puluhan ribu x puluhan ribu
    piksel. Membacanya langsung ke memori (apalagi sebagai float64) bisa memakai
    beberapa GB RAM dan membuat app di-kill oleh server (muncul sebagai halaman
    "Oh no." di Streamlit, bukan pesan error biasa).

    Untuk itu, citra dibaca dalam resolusi yang sudah diperkecil (downsampled)
    langsung dari disk lewat parameter out_shape milik rasterio — jadi RAM yang
    dipakai tetap kecil berapa pun ukuran file aslinya. Ukuran piksel disesuaikan
    proporsional agar estimasi luas tetap akurat.
    """
    jalur_baca = cari_band_pengukuran(jalur_citra)

    with rasterio.open(jalur_baca) as src:
        tinggi_asli, lebar_asli = src.height, src.width
        faktor = max(1, max(tinggi_asli, lebar_asli) // maks_dimensi)
        out_h = max(1, tinggi_asli // faktor)
        out_w = max(1, lebar_asli // faktor)

        data = src.read(
            1,
            out_shape=(out_h, out_w),
            resampling=Resampling.average,
        ).astype(np.float32)

        # Sesuaikan luas per piksel dengan faktor downsample yang dipakai
        res_x = src.res[0] * (lebar_asli / out_w)
        res_y = src.res[1] * (tinggi_asli / out_h)
        pixel_area_m2 = abs(res_x * res_y)

        # Transform & CRS versi resolusi diperkecil — dibutuhkan untuk mengonversi
        # posisi piksel area terdeteksi menjadi koordinat lintang/bujur asli (titik sampling)
        transform_baru = src.transform * src.transform.scale(
            lebar_asli / out_w, tinggi_asli / out_h
        )
        crs_asli = src.crs

    data_dB = 10 * np.log10(np.abs(data) + 1e-10)
    del data  # bebaskan memori array resolusi menengah secepat mungkin

    mask_tumpahan = data_dB < ambang_batas
    piksel_tumpah = int(np.sum(mask_tumpahan))
    luasan_m2 = piksel_tumpah * pixel_area_m2
    luasan_km2 = round(luasan_m2 / 1_000_000, 4)

    return mask_tumpahan, luasan_km2, data_dB, transform_baru, crs_asli, pixel_area_m2


# ---------------------------
# FUNGSI TITIK REKOMENDASI SAMPLING LAPANGAN
# ---------------------------
def hitung_titik_sampling(
    mask, transform, crs, pixel_area_m2,
    jumlah_titik=10, jarak_minimum_antar_titik_m=200,
):
    """
    Mengambil piksel-piksel area terdeteksi (True di mask), mengonversinya ke
    koordinat lintang/bujur, lalu memilih sejumlah `jumlah_titik` titik yang
    PALING DEKAT dengan Pulau Semau (TITIK_ACUAN_SEMAU_LAT/LON) sebagai
    rekomendasi lokasi sampling lapangan (air laut/sedimen).

    Titik-titik dipilih secara greedy dari yang terdekat, dengan jarak minimum
    antar titik (`jarak_minimum_antar_titik_m`) supaya tidak semua titik
    menumpuk di satu area kecil yang sama — biar sebaran sampel representatif.

    SAR hanya mendeteksi KEBERADAAN & LUAS, bukan konsentrasi — titik-titik ini
    adalah usulan lokasi sampling, bukan hasil pengukuran konsentrasi hidrokarbon.
    """
    rows, cols = np.where(mask)
    if len(rows) == 0:
        return pd.DataFrame(columns=[
            "No", "Lintang", "Bujur", "Jarak ke Pulau Semau (m)"
        ])

    # Konversi seluruh piksel terdeteksi ke lon/lat (vectorized)
    xs, ys = pixel_ke_koordinat(transform, rows, cols)
    xs, ys = np.array(xs), np.array(ys)
    if crs is not None and crs.to_epsg() != 4326:
        lons, lats = reproyeksi_koordinat(crs, "EPSG:4326", xs.tolist(), ys.tolist())
        lons, lats = np.array(lons), np.array(lats)
    else:
        lons, lats = xs, ys

    # Jarak tiap piksel ke titik acuan Pulau Semau (aproksimasi datar, cukup
    # akurat untuk area sekecil ini — dalam meter)
    m_per_derajat_lat = 110_540.0
    m_per_derajat_lon = 111_320.0 * np.cos(np.radians(TITIK_ACUAN_SEMAU_LAT))
    dx = (lons - TITIK_ACUAN_SEMAU_LON) * m_per_derajat_lon
    dy = (lats - TITIK_ACUAN_SEMAU_LAT) * m_per_derajat_lat
    jarak_m = np.sqrt(dx**2 + dy**2)

    urutan = np.argsort(jarak_m)  # dari yang terdekat

    titik_terpilih = []
    koord_terpilih = []
    for idx in urutan:
        lon_c, lat_c = lons[idx], lats[idx]
        # Pastikan cukup jauh dari titik yang sudah dipilih (hindari menumpuk)
        cukup_jauh = all(
            np.sqrt(
                ((lon_c - lo) * m_per_derajat_lon) ** 2
                + ((lat_c - la) * m_per_derajat_lat) ** 2
            ) >= jarak_minimum_antar_titik_m
            for lo, la in koord_terpilih
        )
        if cukup_jauh:
            titik_terpilih.append({
                "No": len(titik_terpilih) + 1,
                "Lintang": round(float(lat_c), 6),
                "Bujur": round(float(lon_c), 6),
                "Jarak ke Pulau Semau (m)": round(float(jarak_m[idx]), 1),
            })
            koord_terpilih.append((lon_c, lat_c))
        if len(titik_terpilih) >= jumlah_titik:
            break

    return pd.DataFrame(titik_terpilih)


# ---------------------------
# FUNGSI EKSTRAKSI WAKTU AKUISISI DARI NAMA FILE
# ---------------------------
def ekstrak_waktu_dari_nama(jalur_berkas):
    """
    Nama file Sentinel-1 mengandung timestamp akuisisi, contoh:
    S1D_IW_GRDH_1SDV_20260828T212021_20260828T212050_004331_007FD7_7346.zip
    Fungsi ini mengambil timestamp PERTAMA (waktu mulai rekam) sebagai datetime UTC.
    Mengembalikan None kalau polanya tidak ditemukan.
    """
    nama = os.path.basename(jalur_berkas)
    m = re.search(r"(\d{8})T(\d{6})", nama)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


# ---------------------------
# FUNGSI AMBIL KECEPATAN ANGIN HISTORIS (Open-Meteo Archive API — gratis, tanpa API key)
# ---------------------------
def ambil_kecepatan_angin(lat, lon, waktu_utc):
    """
    Mengambil kecepatan angin 10m (m/s) paling dekat dengan waktu_utc, di koordinat
    yang diberikan, lewat Open-Meteo Historical Weather API.
    """
    tanggal = waktu_utc.strftime("%Y-%m-%d")
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": tanggal,
        "end_date": tanggal,
        "hourly": "windspeed_10m",
        "windspeed_unit": "ms",
        "timezone": "UTC",
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    waktu_list = data.get("hourly", {}).get("time", [])
    angin_list = data.get("hourly", {}).get("windspeed_10m", [])
    if not waktu_list or not angin_list:
        raise ValueError("Data angin tidak tersedia untuk tanggal/lokasi ini.")

    # Cari jam yang paling dekat dengan waktu akuisisi citra
    target = waktu_utc.strftime("%Y-%m-%dT%H:00")
    if target in waktu_list:
        idx = waktu_list.index(target)
    else:
        idx = min(range(len(waktu_list)), key=lambda i: abs(i - waktu_utc.hour))

    return angin_list[idx]


def nilai_validitas_angin(kecepatan_ms):
    """Menilai apakah kecepatan angin berada di rentang valid untuk deteksi SAR."""
    if kecepatan_ms is None:
        return "Tidak diketahui", "warning"
    if kecepatan_ms < AMBANG_ANGIN_MIN_MS:
        return (
            f"⚠️ Terlalu tenang ({kecepatan_ms:.1f} m/s) — risiko salah deteksi "
            f"sebagai look-alike alami (mis. biogenic slick)",
            "warning",
        )
    if kecepatan_ms > AMBANG_ANGIN_MAKS_MS:
        return (
            f"⚠️ Terlalu kencang ({kecepatan_ms:.1f} m/s) — sinyal tumpahan minyak "
            f"berisiko tertutup gelombang",
            "warning",
        )
    return f"✅ Valid ({kecepatan_ms:.1f} m/s) — dalam rentang operasional 3–10 m/s", "success"


# ---------------------------
# FUNGSI RIWAYAT TIME-SERIES
# ---------------------------
KOLOM_RIWAYAT = [
    "Tanggal Citra", "Jam Citra (UTC)", "Luas (km2)", "Ambang (dB)",
    "Kecepatan Angin (m/s)", "Validitas Angin", "Berkas", "Waktu Analisis",
]


def muat_riwayat():
    if os.path.exists(RIWAYAT_CSV):
        return pd.read_csv(RIWAYAT_CSV)
    return pd.DataFrame(columns=KOLOM_RIWAYAT)


def simpan_baris_riwayat(baris: dict):
    os.makedirs(LOKASI_SIMPAN_DATA, exist_ok=True)
    df = muat_riwayat()
    df = pd.concat([df, pd.DataFrame([baris])], ignore_index=True)
    df.to_csv(RIWAYAT_CSV, index=False)
    return df


# ---------------------------
# TAMPILAN APLIKASI
# ---------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🔍 Cari Citra", "📥 Unduh", "📊 Analisis", "📈 Time Series", "🧭 Titik Sampling"]
)

with tab1:
    if st.button("🔍 Cari Citra Satelit", type="primary"):
        try:
            with st.spinner("Mencari citra Sentinel-1 di area kejadian..."):
                daftar_citra = cari_data_sentinel1()
            if daftar_citra:
                st.success(f"✅ Ditemukan {len(daftar_citra)} citra yang sesuai!")
                st.dataframe(daftar_citra, use_container_width=True)
            else:
                st.warning("Tidak ada citra ditemukan untuk area dan rentang tanggal ini.")
        except Exception as e:
            st.error(f"❌ Gagal mencari data: {e}")
            with st.expander("Detail error"):
                st.code(traceback.format_exc())

with tab2:
    st.subheader("Pengunduhan Citra")

    if "berkas_terunduh" not in st.session_state:
        st.session_state.berkas_terunduh = []  # daftar path hasil unduhan sesi ini
    if "berkas_terbaru" not in st.session_state:
        st.session_state.berkas_terbaru = None  # path unduhan paling baru, untuk tombol unduh ke komputer

    tautan = st.text_input("Tempel tautan unduh citra di sini:")
    if st.button("📥 Mulai Unduh") and tautan:
        try:
            sesi = buat_sesi_earthdata()
            with st.spinner("Sedang mengunduh dari NASA Earthdata ke server... ukuran ~1 GB, mohon tunggu..."):
                berkas_lokal = unduh_citra(tautan, sesi)
            st.success(f"✅ Berkas tersimpan di server: `{berkas_lokal}`")

            if berkas_lokal not in st.session_state.berkas_terunduh:
                st.session_state.berkas_terunduh.append(berkas_lokal)
            # otomatis pilih file ini sebagai default di tab Analisis
            st.session_state.jalur_berkas_terpilih = berkas_lokal
            st.session_state.berkas_terbaru = berkas_lokal
            st.info("➡️ File ini sudah otomatis tersedia sebagai pilihan di tab **📊 Analisis**.")
        except Exception as e:
            st.error(f"❌ Gagal mengunduh: {e}")
            with st.expander("Detail error"):
                st.code(traceback.format_exc())

    # ---------------------------
    # TOMBOL UNDUH KE KOMPUTER PENGGUNA
    # ---------------------------
    if st.session_state.berkas_terbaru and os.path.exists(st.session_state.berkas_terbaru):
        st.divider()
        st.markdown("**💾 Simpan file ini ke komputer Anda sendiri:**")
        ukuran_mb = os.path.getsize(st.session_state.berkas_terbaru) / (1024 * 1024)
        st.caption(f"Ukuran berkas: {ukuran_mb:.1f} MB — proses ini memuat seluruh file ke memori, mohon sabar untuk file besar.")
        try:
            with open(st.session_state.berkas_terbaru, "rb") as f:
                st.download_button(
                    label="⬇️ Unduh ke Komputer Saya",
                    data=f,
                    file_name=os.path.basename(st.session_state.berkas_terbaru),
                    mime="application/zip",
                )
        except Exception as e:
            st.error(f"❌ Gagal menyiapkan file untuk diunduh: {e}")

with tab3:
    st.subheader("Analisis & Deteksi Tumpahan")

    if "berkas_terunduh" not in st.session_state:
        st.session_state.berkas_terunduh = []
    if "jalur_berkas_terpilih" not in st.session_state:
        st.session_state.jalur_berkas_terpilih = ""

    jalur_berkas = ""

    if st.session_state.berkas_terunduh:
        opsi = ["-- pilih dari hasil unduhan --"] + st.session_state.berkas_terunduh
        default_idx = (
            opsi.index(st.session_state.jalur_berkas_terpilih)
            if st.session_state.jalur_berkas_terpilih in opsi
            else 0
        )
        pilihan = st.selectbox(
            "📂 Pilih file yang sudah diunduh sebelumnya:",
            options=opsi,
            index=default_idx,
        )
        if pilihan != "-- pilih dari hasil unduhan --":
            jalur_berkas = pilihan

        st.caption("Belum ada file yang cocok? Isi manual di kolom bawah ini ⬇️")

    jalur_manual = st.text_input(
        "Atau tempel manual jalur berkas citra (.zip atau .tiff):",
        value=jalur_berkas,
    )
    if jalur_manual:
        jalur_berkas = jalur_manual

    ambang_pilih = st.slider("Ambang batas deteksi (dB)", -30, -10, AMBANG_BATAS_DETEKSI)
    st.caption(
        "ℹ️ Citra otomatis diproses dalam resolusi yang diperkecil untuk menghindari "
        "kehabisan memori server. Ini memengaruhi tingkat detail, bukan validitas "
        "perkiraan luas area secara keseluruhan."
    )

    if st.button("🚀 Jalankan Analisis") and jalur_berkas:
        try:
            with st.spinner("Memproses citra..."):
                mask, luas, dB_data, transform_citra, crs_citra, pixel_area_m2 = deteksi_tumpahan(
                    jalur_berkas, ambang_pilih
                )
            st.metric("📐 Luas perkiraan tumpahan", f"{luas} km²")
            st.info(f"Ambang batas yang digunakan: {ambang_pilih} dB")
            st.warning("⚠️ Hasil berupa perkiraan — perlu verifikasi lapangan atau visual.")

            # ---------------------------
            # WAKTU AKUISISI + VALIDASI ANGIN
            # ---------------------------
            st.markdown("### 🌬️ Validasi Kecepatan Angin")
            waktu_citra = ekstrak_waktu_dari_nama(jalur_berkas)

            if waktu_citra is None:
                st.caption(
                    "Tidak bisa membaca tanggal/jam otomatis dari nama file. "
                    "Isi manual di bawah untuk validasi angin:"
                )
                col_a, col_b = st.columns(2)
                tgl_manual = col_a.date_input("Tanggal akuisisi citra")
                jam_manual = col_b.time_input("Jam akuisisi (UTC)")
                waktu_citra = datetime.combine(tgl_manual, jam_manual).replace(tzinfo=timezone.utc)

            kecepatan_angin = None
            try:
                with st.spinner("Mengambil data angin historis (Open-Meteo)..."):
                    kecepatan_angin = ambil_kecepatan_angin(CENTROID_LAT, CENTROID_LON, waktu_citra)
                pesan_validitas, tipe_pesan = nilai_validitas_angin(kecepatan_angin)
                col_x, col_y = st.columns(2)
                col_x.metric("💨 Kecepatan angin saat akuisisi", f"{kecepatan_angin:.1f} m/s")
                if tipe_pesan == "success":
                    col_y.success(pesan_validitas)
                else:
                    col_y.warning(pesan_validitas)
            except Exception as e:
                st.warning(f"Tidak bisa mengambil data angin: {e}")

            # ---------------------------
            # SIMPAN KE RIWAYAT TIME-SERIES
            # ---------------------------
            simpan_baris_riwayat({
                "Tanggal Citra": waktu_citra.strftime("%Y-%m-%d"),
                "Jam Citra (UTC)": waktu_citra.strftime("%H:%M"),
                "Luas (km2)": luas,
                "Ambang (dB)": ambang_pilih,
                "Kecepatan Angin (m/s)": round(kecepatan_angin, 1) if kecepatan_angin is not None else None,
                "Validitas Angin": nilai_validitas_angin(kecepatan_angin)[0] if kecepatan_angin is not None else "Tidak diketahui",
                "Berkas": os.path.basename(jalur_berkas),
                "Waktu Analisis": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            })
            st.success("📈 Hasil analisis ini sudah ditambahkan ke tab **Time Series**.")

            # ---------------------------
            # HITUNG TITIK REKOMENDASI SAMPLING
            # ---------------------------
            try:
                if luas > 0:
                    df_titik = hitung_titik_sampling(
                        mask, transform_citra, crs_citra, pixel_area_m2
                    )
                    st.session_state.df_titik_sampling = df_titik
                    st.session_state.info_titik_sampling = {
                        "Berkas": os.path.basename(jalur_berkas),
                        "Tanggal Citra": waktu_citra.strftime("%Y-%m-%d %H:%M UTC"),
                    }
                    st.success(
                        f"🧭 {len(df_titik)} titik rekomendasi sampling sudah dihitung — "
                        "cek tab **🧭 Titik Sampling**."
                    )
                else:
                    st.session_state.df_titik_sampling = None
            except Exception as e:
                st.warning(f"Tidak bisa menghitung titik sampling: {e}")
        except Exception as e:
            st.error(f"❌ Gagal memproses citra: {e}")
            with st.expander("Detail error"):
                st.code(traceback.format_exc())

with tab4:
    st.subheader("📈 Perubahan Luas Tumpahan dari Waktu ke Waktu")

    df_riwayat = muat_riwayat()

    if df_riwayat.empty:
        st.info(
            "Belum ada data riwayat. Jalankan analisis di tab **📊 Analisis** terlebih "
            "dahulu — setiap hasil analisis otomatis tercatat di sini."
        )
    else:
        df_plot = df_riwayat.copy()
        df_plot["Tanggal Citra"] = pd.to_datetime(df_plot["Tanggal Citra"])
        df_plot = df_plot.sort_values("Tanggal Citra")

        st.line_chart(df_plot.set_index("Tanggal Citra")["Luas (km2)"])

        st.markdown("**Tabel riwayat lengkap:**")
        st.dataframe(df_riwayat, use_container_width=True)

        col1, col2, col3 = st.columns(3)

        with col1:
            st.download_button(
                "⬇️ Unduh Riwayat (.csv)",
                data=df_riwayat.to_csv(index=False).encode("utf-8"),
                file_name="riwayat_analisis_tumpahan_minyak.csv",
                mime="text/csv",
            )

        with col2:
            if st.button("🗑️ Hapus Semua Riwayat"):
                if os.path.exists(RIWAYAT_CSV):
                    os.remove(RIWAYAT_CSV)
                st.rerun()

    st.divider()
    st.markdown("**📤 Muat riwayat lama** (misalnya setelah app di-reboot dan data sebelumnya hilang):")
    berkas_riwayat_lama = st.file_uploader("Upload file riwayat_analisis.csv sebelumnya", type=["csv"])
    if berkas_riwayat_lama is not None:
        try:
            df_lama = pd.read_csv(berkas_riwayat_lama)
            df_gabung = pd.concat([muat_riwayat(), df_lama], ignore_index=True).drop_duplicates()
            os.makedirs(LOKASI_SIMPAN_DATA, exist_ok=True)
            df_gabung.to_csv(RIWAYAT_CSV, index=False)
            st.success(f"✅ {len(df_lama)} baris riwayat berhasil digabungkan.")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Gagal membaca file riwayat: {e}")

with tab5:
    st.subheader("🧭 10 Titik Rekomendasi Sampling Terdekat dengan Pulau Semau")

    st.info("""
📌 **Penting:** SAR hanya mendeteksi keberadaan & luas tumpahan, BUKAN konsentrasi
hidrokarbon. 10 titik di bawah ini adalah rekomendasi LOKASI di area terdeteksi yang
paling dekat dengan Pulau Semau, untuk pengambilan sampel air/sedimen oleh tim lapangan
— konsentrasi hidrokarbon (TPH/PAH) hanya bisa diketahui lewat analisis laboratorium
(GC-MS) atas sampel yang diambil di titik-titik ini. Diurutkan dari yang paling dekat.
""")

    if "df_titik_sampling" not in st.session_state:
        st.session_state.df_titik_sampling = None

    df_titik = st.session_state.df_titik_sampling

    if df_titik is None or df_titik.empty:
        st.warning(
            "Belum ada titik sampling. Jalankan analisis di tab **📊 Analisis** terlebih "
            "dahulu pada citra yang menunjukkan area terdeteksi (luas > 0)."
        )
    else:
        info = st.session_state.get("info_titik_sampling", {})
        if info:
            st.caption(f"Dihitung dari citra: `{info.get('Berkas', '-')}` — {info.get('Tanggal Citra', '-')}")

        st.markdown("**Tabel koordinat titik sampling:**")
        st.dataframe(df_titik, use_container_width=True)

        st.markdown("**Peta sebaran titik:**")
        df_peta = df_titik.rename(columns={"Lintang": "lat", "Bujur": "lon"})[["lat", "lon"]]
        st.map(df_peta, zoom=11)

        st.download_button(
            "⬇️ Unduh Titik Sampling (.csv)",
            data=df_titik.to_csv(index=False).encode("utf-8"),
            file_name="titik_rekomendasi_sampling.csv",
            mime="text/csv",
        )

        st.caption(
            "💡 Tip: buka file CSV ini di Google Maps / Google Earth (fitur 'Import') atau "
            "aplikasi GPS lapangan untuk navigasi langsung ke titik-titik sampling."
        )

st.divider()
st.caption("""
📌 Catatan:
- Area pencarian sudah diperkecil di sekitar titik kejadian.
- Login NASA Earthdata (sidebar kiri) wajib diisi sebelum mengunduh citra.
- Ukuran 1 berkas citra Sentinel-1 GRD sekitar 1 GB.
""")
