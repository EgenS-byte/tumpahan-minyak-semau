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


def buat_sesi_earthdata():
    """Buat sesi terautentikasi ke NASA Earthdata untuk keperluan unduh."""
    if not earthdata_user or not earthdata_pass:
        return None
    try:
        return asf.ASFSession().auth_with_creds(earthdata_user, earthdata_pass)
    except Exception as e:
        st.sidebar.error(f"Gagal login Earthdata: {e}")
        return None


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
            "Belum login ke NASA Earthdata. Isi username & password di sidebar terlebih dahulu."
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
    tautan = st.text_input("Tempel tautan unduh citra di sini:")
    if st.button("📥 Mulai Unduh") and tautan:
        try:
            sesi = buat_sesi_earthdata()
            with st.spinner("Sedang mengunduh... ukuran ~1 GB, mohon tunggu..."):
                berkas_lokal = unduh_citra(tautan, sesi)
            st.success(f"✅ Berkas tersimpan di: `{berkas_lokal}`")
        except Exception as e:
            st.error(f"❌ Gagal mengunduh: {e}")
            with st.expander("Detail error"):
                st.code(traceback.format_exc())

with tab3:
    st.subheader("Analisis & Deteksi Tumpahan")
    jalur_berkas = st.text_input("Jalur berkas citra (.zip atau .tiff) yang sudah diunduh:")
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
