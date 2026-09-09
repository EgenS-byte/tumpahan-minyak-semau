# ============================================================
# APLIKASI PEMANTAUAN TUMPAHAN MINYAK — PULAU SEMAU, NTT
# Area: Diperkecil — Sekitar KM Kuala Emas
# Metode: Menggunakan ASFSearchOptions (aman & tahan-versi)
# ============================================================

import os
import zipfile
import traceback

import asf_search as asf
import rasterio
import numpy as np
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
def deteksi_tumpahan(jalur_citra, ambang_batas=AMBANG_BATAS_DETEKSI):
    jalur_baca = cari_band_pengukuran(jalur_citra)

    with rasterio.open(jalur_baca) as src:
        data = src.read(1).astype(np.float64)
        pixel_area_m2 = abs(src.res[0] * src.res[1])

    data_dB = 10 * np.log10(np.abs(data) + 1e-10)
    mask_tumpahan = data_dB < ambang_batas
    piksel_tumpah = int(np.sum(mask_tumpahan))
    luasan_m2 = piksel_tumpah * pixel_area_m2
    luasan_km2 = round(luasan_m2 / 1_000_000, 4)

    return mask_tumpahan, luasan_km2, data_dB


# ---------------------------
# TAMPILAN APLIKASI
# ---------------------------
tab1, tab2, tab3 = st.tabs(["🔍 Cari Citra", "📥 Unduh", "📊 Analisis"])

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

    if st.button("🚀 Jalankan Analisis") and jalur_berkas:
        try:
            with st.spinner("Memproses citra..."):
                mask, luas, dB_data = deteksi_tumpahan(jalur_berkas, ambang_pilih)
            st.metric("📐 Luas perkiraan tumpahan", f"{luas} km²")
            st.info(f"Ambang batas yang digunakan: {ambang_pilih} dB")
            st.warning("⚠️ Hasil berupa perkiraan — perlu verifikasi lapangan atau visual.")
        except Exception as e:
            st.error(f"❌ Gagal memproses citra: {e}")
            with st.expander("Detail error"):
                st.code(traceback.format_exc())

st.divider()
st.caption("""
📌 Catatan:
- Area pencarian sudah diperkecil di sekitar titik kejadian.
- Login NASA Earthdata (sidebar kiri) wajib diisi sebelum mengunduh citra.
- Ukuran 1 berkas citra Sentinel-1 GRD sekitar 1 GB.
""")
