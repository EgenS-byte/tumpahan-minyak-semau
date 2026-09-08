# ============================================================
# APLIKASI PEMANTAUAN TUMPAHAN MINYAK — PULAU SEMAU, NTT
# Periode: 29 Juli – 31 Agustus 2026
# Area: Diperkecil — Sekitar KM Kuala Emas
# Sumber Data: Sentinel-1 (SAR) — ASF DAAC NASA
# ============================================================

import os
import asf_search as asf
import rasterio
import numpy as np
import streamlit as st

st.set_page_config(page_title="Pemantauan Tumpahan Minyak — Pulau Semau", layout="wide")

# ---------------------------
# KONFIGURASI — AREA DIPERKECIL
# ---------------------------
# Batas presisi: Pusat kejadian KM Kuala Emas — 10.18° LS, 123.55° BT
BBOX = [
    123.50,   # Bujur Barat
    -10.22,   # Lintang Selatan
    123.60,   # Bujur Timur
    -10.14    # Lintang Utara
]

START_DATE = "2026-07-29T00:00:00Z"
END_DATE   = "2026-08-31T23:59:59Z"

AMBANG_BATAS_DETEKSI = -18
LOKASI_SIMPAN_DATA   = "./data/"

# ---------------------------
# JUDUL & INFORMASI
# ---------------------------
st.title("🛰️ Pemantauan Tumpahan Minyak — Pulau Semau, NTT")
st.subheader("Periode: 29 Juli – 31 Agustus 2026")

st.info("""
📍 Lokasi: Perairan Pulau Semau, Kab. Kupang, NTT
🔑 Titik pusat kejadian: 10.18° LS, 123.55° BT (KM Kuala Emas)
🛰️ Sumber data: Sentinel-1 (SAR) — ASF DAAC NASA
📏 Area pencarian: ±9 km² di sekitar titik kejadian
""")

# ---------------------------
# FUNGSI CARI DATA SATELIT
# ---------------------------
def cari_data_sentinel1():
    hasil = asf.search(
        collections=["SENTINEL-1"],
        processingLevel="GRD",
        beamMode="IW",
        polarization="VV+VH",
        startDateTime=START_DATE,
        endDateTime=END_DATE,
        bbox=BBOX
    )
    
    daftar_hasil = []
    for citra in hasil:
        props = citra.properties
        daftar_hasil.append({
            "Tanggal Rekam": props.get("startTime", "")[:10],
            "Jam Rekam":     props.get("startTime", "")[11:16],
            "Produk":        props.get("processingLevel", ""),
            "Resolusi":      props.get("resolution", ""),
            "Tautan Unduh":  props.get("url", "")
        })
    return daftar_hasil

# ---------------------------
# FUNGSI UNDUH CITRA
# ---------------------------
def unduh_citra(tautan):
    os.makedirs(LOKASI_SIMPAN_DATA, exist_ok=True)
    asf.download_url(tautan, path=LOKASI_SIMPAN_DATA)
    nama_berkas = os.path.join(LOKASI_SIMPAN_DATA, tautan.split("/")[-1])
    return nama_berkas

# ---------------------------
# FUNGSI DETEKSI TUMPAHAN
# ---------------------------
def deteksi_tumpahan(jalur_citra, ambang_batas=AMBANG_BATAS_DETEKSI):
    with rasterio.open(jalur_citra) as src:
        data = src.read(1)
        meta = src.meta

    data_dB = 10 * np.log10(np.absolute(data) + 1e-10)
    mask_tumpahan = data_dB < ambang_batas
    piksel_tumpah = np.sum(mask_tumpahan)
    luasan_m2  = piksel_tumpah * 100
    luasan_km2 = round(luasan_m2 / 1_000_000, 4)

    return mask_tumpahan, luasan_km2, data_dB

# ---------------------------
# TAMPILAN APLIKASI
# ---------------------------
tab1, tab2, tab3 = st.tabs(["🔍 Cari Citra", "📥 Unduh", "📊 Analisis"])

with tab1:
    if st.button("🔍 Cari Citra Satelit", type="primary"):
        with st.spinner("Mencari citra Sentinel-1 di area kejadian..."):
            daftar_citra = cari_data_sentinel1()
            st.success(f"✅ Ditemukan {len(daftar_citra)} citra yang sesuai!")
            st.dataframe(daftar_citra, use_container_width=True)

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
- Area pencarian sudah diperkecil: ±9 km² di sekitar titik kejadian KM Kuala Emas
- Pastikan sudah memiliki akun NASA Earthdata sebelum mengunduh.
- Ukuran 1 berkas citra Sentinel-1 GRD sekitar 1 GB.
""")
