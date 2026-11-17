"""
Almacen de capturas crudas de cadenas, detras de una interfaz minima.

La captura prospectiva (A5 de PAPS_PROBEDGE_PLAN.md) corre hoy con timers de systemd
en la maquina de Leo y despues como cron de Render. Los cron de Render no tienen disco
persistente, asi que el destino tiene que poder cambiar sin tocar el script:

    PROBEDGE_STORE=local   (default)  archivos bajo PROBEDGE_STORE_DIR (default data/raw)
    PROBEDGE_STORE=s3                 bucket S3 o compatible (Cloudflare R2, Backblaze B2)
        PROBEDGE_S3_BUCKET   nombre del bucket (obligatorio)
        PROBEDGE_S3_PREFIX   prefijo dentro del bucket (default probedge/raw)
        PROBEDGE_S3_ENDPOINT URL del endpoint para proveedores compatibles (R2: https://<cuenta>.r2.cloudflarestorage.com)
        Credenciales: la cadena estandar de boto3 (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY en el entorno).

Las llaves son rutas relativas con "/" (p. ej. "tradier/SPY/2026-11-17/1000.json.gz").
Escritura atomica en local (archivo temporal y rename) para que una corrida cortada no
deje un archivo a medias que la siguiente tome por bueno.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional, Protocol

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


class ChainStore(Protocol):
    def exists(self, key: str) -> bool: ...
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def list(self, prefix: str) -> list[str]: ...


class LocalStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or DEFAULT_DIR)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"llave fuera del almacen: {key!r}")
        return p

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def put(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
        return str(p)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root.resolve()
        if not base.exists():
            return []
        root = self.root.resolve()
        return sorted(str(f.relative_to(root)).replace(os.sep, "/") for f in base.rglob("*") if f.is_file()
                      and not f.name.endswith(".part"))

    def __repr__(self) -> str:
        return f"LocalStore({self.root})"


class S3Store:
    """S3 o compatible. `client` se inyecta en pruebas; en produccion se crea con boto3 (dependencia opcional)."""

    def __init__(self, bucket: str, prefix: str = "probedge/raw", *, endpoint_url: Optional[str] = None,
                 client=None) -> None:
        if not bucket:
            raise ValueError("PROBEDGE_S3_BUCKET vacio")
        self.bucket, self.prefix = bucket, prefix.strip("/")
        if client is None:
            import boto3  # opcional: solo se necesita con PROBEDGE_STORE=s3
            client = boto3.client("s3", endpoint_url=endpoint_url or None)
        self.client = client

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key.lstrip('/')}" if self.prefix else key.lstrip("/")

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except Exception as exc:  # botocore ClientError 404; cualquier otra cosa se propaga
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def put(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)
        return f"s3://{self.bucket}/{self._key(key)}"

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()

    def list(self, prefix: str) -> list[str]:
        out: list[str] = []
        token = None
        full = self._key(prefix)
        while True:
            kw = {"Bucket": self.bucket, "Prefix": full}
            if token:
                kw["ContinuationToken"] = token
            resp = self.client.list_objects_v2(**kw)
            cut = len(self.prefix) + 1 if self.prefix else 0
            out += [o["Key"][cut:] for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return sorted(out)
            token = resp.get("NextContinuationToken")

    def __repr__(self) -> str:
        return f"S3Store(s3://{self.bucket}/{self.prefix})"


def get_store(environ: Optional[dict] = None) -> ChainStore:
    env = os.environ if environ is None else environ
    kind = (env.get("PROBEDGE_STORE") or "local").strip().lower()
    if kind == "local":
        d = env.get("PROBEDGE_STORE_DIR")
        return LocalStore(Path(d) if d else None)
    if kind == "s3":
        return S3Store(env.get("PROBEDGE_S3_BUCKET", ""), env.get("PROBEDGE_S3_PREFIX", "probedge/raw"),
                       endpoint_url=env.get("PROBEDGE_S3_ENDPOINT"))
    raise ValueError(f"PROBEDGE_STORE={kind!r}; use local o s3")


def keys_for_day(store: ChainStore, source: str, day: str, symbols: Iterable[str]) -> list[str]:
    """Llaves capturadas de una fuente en un dia (para resumenes y para el respaldo)."""
    out: list[str] = []
    for s in symbols:
        out += store.list(f"{source}/{s.upper()}/{day}")
    return out
