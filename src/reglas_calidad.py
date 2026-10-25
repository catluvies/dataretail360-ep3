"""Reglas de calidad reutilizables: funciones puras que usa la capa Silver.

Cada función resuelve un problema del diagnóstico de la EP1:
    unicidad     -> normalizar_rut, normalizar_email (llaves para deduplicar)
    validez      -> parsear_fecha, parsear_monto, email_valido, rut_valido
    consistencia -> normalizar_texto, normalizar_estado
"""
import hashlib
import re

import pandas as pd

PATRON_EMAIL = r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$"
FORMATOS_FECHA = ["%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M:%S"]
EQUIVALENCIAS_ESTADO = {
    "COMPLETADA": "COMPLETADA", "PAGADO": "COMPLETADA",
    "ANULADA": "ANULADA", "ANULADO": "ANULADA",
    "DEVUELTA": "DEVUELTA", "DEVUELTO": "DEVUELTA",
}


def digito_verificador(numero: int) -> str:
    """Dígito verificador del RUT chileno (módulo 11)."""
    suma, factor = 0, 2
    for digito in reversed(str(numero)):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def normalizar_rut(valor) -> str | None:
    """'12.345.678-5', '12345678-5' y '123456785' -> '12345678-5'."""
    if valor is None or pd.isna(valor):
        return None
    limpio = re.sub(r"[^0-9kK]", "", str(valor)).upper()
    if len(limpio) < 2 or not limpio[:-1].isdigit():
        return None
    return f"{int(limpio[:-1])}-{limpio[-1]}"


def rut_valido(rut_normalizado: str | None) -> bool:
    if rut_normalizado is None or pd.isna(rut_normalizado) or not rut_normalizado:
        return False
    cuerpo, dv = rut_normalizado.split("-")
    return digito_verificador(int(cuerpo)) == dv


def normalizar_email(serie: pd.Series) -> pd.Series:
    limpio = serie.astype("string").str.strip().str.lower()
    return limpio.mask(limpio == "")


def email_valido(serie: pd.Series) -> pd.Series:
    return serie.astype("string").str.match(PATRON_EMAIL).fillna(False).astype(bool)


def normalizar_texto(serie: pd.Series) -> pd.Series:
    """Quita espacios sobrantes; deja vacíos como nulos."""
    limpio = serie.astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
    return limpio.mask(limpio == "")


def nombre_propio(serie: pd.Series) -> pd.Series:
    """'JUAN PÉREZ' o 'juan pérez' -> 'Juan Pérez'."""
    return normalizar_texto(serie).str.title()


def parsear_fecha(serie: pd.Series) -> pd.Series:
    """Prueba cada formato conocido; lo que no calza con ninguno queda NaT."""
    texto = serie.astype("string").str.strip()
    resultado = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[us]")
    for formato in FORMATOS_FECHA:
        pendiente = resultado.isna()
        if not pendiente.any():
            break
        resultado[pendiente] = pd.to_datetime(texto[pendiente], format=formato, errors="coerce")
    return resultado


def parsear_monto(serie: pd.Series) -> pd.Series:
    """'$19.990', '19990', '-19990' -> número. Texto no numérico -> NaN."""
    texto = serie.astype("string").str.strip().str.replace(r"[$\s]", "", regex=True).str.replace(".", "", regex=False)
    return pd.to_numeric(texto, errors="coerce")


def normalizar_estado(serie: pd.Series) -> pd.Series:
    """Homologa los estados de POS y e-commerce a COMPLETADA / ANULADA / DEVUELTA."""
    return serie.astype("string").str.strip().str.upper().map(EQUIVALENCIAS_ESTADO)


def seudonimizar(rut_normalizado: str, sal: str) -> str:
    """Seudónimo estable del RUT: permite seguir al cliente sin exponer su identidad."""
    return hashlib.sha256(f"{sal}|{rut_normalizado}".encode()).hexdigest()[:16]


def enmascarar(valor) -> str | None:
    """Oculta datos personales dejando solo los últimos 3 caracteres."""
    if valor is None or pd.isna(valor) or str(valor) == "":
        return valor
    texto = str(valor)
    return "*" * max(len(texto) - 3, 0) + texto[-3:]
