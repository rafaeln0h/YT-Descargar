import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

FFMPEG_DIR = Path(__file__).parent / 'ffmpeg_portable'
FFMPEG_BIN = FFMPEG_DIR / 'bin' / 'ffmpeg.exe'
FFPROBE_BIN = FFMPEG_DIR / 'bin' / 'ffprobe.exe'


def check_ffmpeg():
    """Devuelve el directorio de una pareja FFmpeg/ffprobe válida."""
    if FFMPEG_BIN.is_file() and FFPROBE_BIN.is_file():
        return str(FFMPEG_BIN.parent)
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if ffmpeg and ffprobe:
        return str(Path(ffmpeg).resolve().parent)
    return None


def _safe_extract(zip_ref, destination):
    """Extrae sin permitir rutas absolutas o traversal dentro del ZIP."""
    destination = Path(destination).resolve()
    for member in zip_ref.infolist():
        target = (destination / member.filename).resolve()
        try:
            target.relative_to(destination)
        except ValueError as exc:
            raise ValueError(f"Entrada ZIP insegura: {member.filename}") from exc
    zip_ref.extractall(destination)


def download_ffmpeg():
    """Descarga FFmpeg portable para Windows"""
    if os.name != 'nt':
        print("[AVISO] La descarga automática de FFmpeg sólo está disponible en Windows.")
        print("[TIP] Instala ffmpeg y ffprobe con el gestor de paquetes de tu sistema.")
        return False
    print("[SETUP] Descargando FFmpeg portable (100-150 MB)...")
    print("[SETUP] Esto puede tomar varios minutos...")

    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = FFMPEG_DIR / 'ffmpeg.zip'

    try:
        url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        print("[DESCARGA] Conectando a GitHub...")

        class ProgressBar:
            def __init__(self):
                self.last_print = 0

            def __call__(self, block_num, block_size, total_size):
                downloaded = block_num * block_size
                if total_size > 0:
                    percent = min(downloaded * 100 / total_size, 100)
                    if percent - self.last_print >= 5 or percent == 100:
                        mb_downloaded = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        print(f"[DESCARGA] {percent:.0f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)")
                        self.last_print = percent

        progress = ProgressBar()
        urllib.request.urlretrieve(url, zip_path, reporthook=progress)
        print("[OK] Descarga completada")

        print("[SETUP] Extrayendo archivos...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            _safe_extract(zip_ref, FFMPEG_DIR / 'temp')

        bin_dir = FFMPEG_DIR / 'bin'
        bin_dir.mkdir(parents=True, exist_ok=True)

        print("[SETUP] Buscando executables...")
        found_count = 0
        for root, dirs, files in os.walk(FFMPEG_DIR / 'temp'):
            for file in files:
                if file in ['ffmpeg.exe', 'ffprobe.exe']:
                    src = Path(root) / file
                    dst = bin_dir / file
                    print(f"[COPIA] {file}...")
                    shutil.copy2(src, dst)
                    found_count += 1

        if found_count < 2:
            print(f"[AVISO] Solo se encontraron {found_count}/2 archivos")

        print("[LIMPIEZA] Eliminando archivos temporales...")
        shutil.rmtree(FFMPEG_DIR / 'temp', ignore_errors=True)
        zip_path.unlink(missing_ok=True)

        print("[OK] FFmpeg instalado exitosamente")
        return bool(check_ffmpeg())

    except Exception as e:
        print(f"[ERROR] {e}")
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        return False

def setup_ffmpeg_path():
    """Configura la ruta de FFmpeg"""
    bin_path = str(FFMPEG_DIR / 'bin')
    if 'PATH' in os.environ:
        if bin_path not in os.environ['PATH']:
            os.environ['PATH'] = bin_path + os.pathsep + os.environ['PATH']
    else:
        os.environ['PATH'] = bin_path
    return bin_path


def ensure_ffmpeg():
    """Asegura que FFmpeg este disponible"""
    print("\n[SETUP] Verificando FFmpeg...")

    detected = check_ffmpeg()
    if detected:
        print("[OK] FFmpeg ya esta instalado")
        if Path(detected) == FFMPEG_BIN.parent.resolve():
            setup_ffmpeg_path()
        return detected

    print("[AVISO] FFmpeg no encontrado - Descargando...")
    if download_ffmpeg():
        detected = check_ffmpeg()
        if detected:
            setup_ffmpeg_path()
        print(f"[OK] FFmpeg configurado en: {detected}")
        return detected
    else:
        print("[ERROR] No se pudo instalar FFmpeg")
        print("Intenta ejecutar: python setup_ffmpeg.py")
        return None


if __name__ == '__main__':
    bin_path = ensure_ffmpeg()
    sys.exit(0 if bin_path else 1)
