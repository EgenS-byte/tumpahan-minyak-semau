# ============================================================
# APLIKASI PEMANTAUAN TUMPAHAN MINYAK — PULAU SEMAU, NTT
# Periode: 29 Juli – 31 Agustus 2026
# Sumber Data: Sentinel-1 (SAR) — ASF DAAC NASA
# ============================================================

# ⚠️ IMPOR PUSTAKA WAJIB DI PALING ATAS!
import os
import asf_search as asf
import rasterio
import numpy as np
import streamlit as st
from datetime import datetime

# ✅ BARIS INI HARUS SETELAH IMPORT & SEBELUM PERINTAH ST LAINNYA
st.set_page_config(page_title="Pemantauan Tumpahan Minyak — Pulau Semau", layout="wide")

# ---------------------------
# KONFIGURASI DASAR
# ---------------------------
BBOX = {
    "min_lon": 123.45,
    "max_lon": 123.65,
    "min_lat": -10.30,
    "max_lat": -10.10,
}

START_DATE = "2026-07-29"
END_DATE   = "2026-08-31"

PLATFORM      = "SENTINEL-1"
PRODUCT_TYPE  = "GRD"
BEAM_MODE     = "IW"
POLARISATION  = "VV+VH"

AMBANG_BATAS_DETEKSI = -18  # dB — sesuaikan jika perlu
LOKASI_SIMPAN_DATA   = "./data/"

# ---------------------------
# ANTARMUKA APLIKASI
# ---------------------------
st.title("🛰️ Pemantauan Tumpahan Minyak — Pulau Semau, NTT")
st.subheader("Periode: 29 Juli – 31 Agustus 2026")

st.info("""
📍 Lokasi: Perairan Pulau Semau, Kab. Kupang, NTT
🔑 Sumber kejadian: Kebocoran KM Kuala Emas, 29 Juli 2026
🛰️ Sumber data: Sentinel-1 (SAR) — ASF DAAC NASA
""")

# ---------------------------
# FUNGSI: CARI DATA SATELIT
# ---------------------------
def cari_data_sentinel1():
    hasil = asf.search(
        platform=PLATFORM,
        processingLevel=PRODUCT_TYPE,
        beamMode=BEAM_MODE,
        polarization=POLARISATION,
        start=datetime.fromisoformat(START_DATE),
        end=datetime.fromisoformat(END_DATE),
        bbox=[
            BBOX["min_lon"], BBOX["min_lat"],
            BBOX["max_lon"], BBOX["max_lat"]
        ]
    )
    return hasil

# ---------------------------
# FUNGSI: UNDUH CITRA
# ---------------------------
def unduh_citra(tautan):
    os.makedirs(LOKASI_SIMPAN_DATA, exist_ok=True)
    asf.download_url(tautan, path=LOKASI_SIMPAN_DATA)
    nama_berkas = os.path.join(LOKASI_SIMPAN_DATA, tautan.split("/")[-1])
    return nama_berkas

# ---------------------------
# FUNGSI: DETEKSI TUMPAHAN
# ---------------------------
def deteksi_tumpahan(jalur_citra, ambang_batas=AMBANG_BATAS_DETEKSI):
    with rasterio.open(jalur_citra) as src:
        data = src.read(1)  # Band VV
        meta = src.meta

    # Konversi ke desibel (dB)
    data_dB = 10 * np.log10(np.absolute(data) + 1e-10)

    # Area di bawah ambang batas = calon tumpahan minyak
    mask_tumpahan = data_dB < ambang_batas

    # Hitung luasan (asumsi piksel 10m × 10m = 100 m²)
    piksel_tumpah = np.sum(mask_tumpahan)
    luasan_m2  = piksel_tumpah * 100
    luasan_km2 = round(luasan_m2 / 1_000_000, 4)

    return mask_tumpahan, luasan_km2, data_dB

# ---------------------------
# ALUR UTAMA APLIKASI
# ---------------------------
tab1, tab2, tab3 = st.tabs(["🔍 Cari Citra", "📥 Unduh", "📊 Analisis"])

with tab1:
    if st.button("🔍 Cari Citra Satelit", type="primary"):
        with st.spinner("Mencari citra Sentinel-1 yang mencakup area..."):
            daftar_citra = cari_data_sentinel1()
            st.success(f"✅ Ditemukan {len(daftar_citra)} citra yang sesuai!")

            data_tabel = []
            for citra in daftar_citra:
                data_tabel.append({
                    "Tanggal Rekam": citra.properties["startTime"][:10],
                    "Jam Rekam":     citra.properties["startTime"][11:16],
                    "Produk":        citra.properties["productType"],
                    "Resolusi":      citra.properties["resolution"],
                    "Tautan Unduh":  citra.properties["url"]
                })
            st.dataframe(data_tabel, use_container_width=True)

with tab2:
    st.subheader("Pengunduhan Citra")
    tautan = st.text_input("Tempel tautan unduh citra di sini:")
    if st.button("📥 Mulai Unduh") and tautan:
        with st.spinner("Sedang mengunduh... ukuran ~1 GB, mohon tunggu..."):
            berkas_lokal = unduh_citra(tautan)
            st.success(f"✅ Berkas tersimpan di: `{berkas_lokal}`")

with tab3:
    st.subheader("Analisis & Deteksi Tumpahan")
    jalur_berkas = st.text_input("Jalur berkas citra yang sudah diunduh:")
    ambang_pilih = st.slider("Ambang batas deteksi (dB)", -30, -10, AMBANG_BATAS_DETEKSI)

    if st.button("🚀 Jalankan Analisis") and jalur_berkas:
        with st.spinner("Memproses citra..."):
            mask, luas, dB_data = deteksi_tumpahan(jalur_berkas, ambang_pilih)
            st.metric("📐 Luas perkiraan tumpahan", f"{luas} km²")
            st.info(f"Ambang batas yang digunakan: {ambang_pilih} dB")
            st.warning("⚠️ Hasil berupa perkiraan — perlu verifikasi lapangan atau visual.")

st.divider()
st.caption("""
📌 Catatan:
- Pastikan sudah memiliki akun NASA Earthdata dan telah login sebelum mengunduh.
- Ukuran 1 berkas citra Sentinel-1 GRD sekitar 1 GB.
- Hasil deteksi perlu verifikasi karena faktor laut, angin, dan sedimen.
""")
