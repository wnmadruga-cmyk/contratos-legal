"""
Camada de storage de arquivos com driver pattern.

Drivers:
- LocalStorage:    grava em ./uploads/leads/<lead_id>/<key>  (default)
- S3Storage:       boto3 (lazy import)
- SupabaseStorage: supabase-py (lazy import)

Seleção via env:
    LEADS_STORAGE_DRIVER = local | s3 | supabase     (default: local)

Para S3:
    LEADS_S3_BUCKET, LEADS_S3_REGION,
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (boto3 lê do env padrão)

Para Supabase:
    LEADS_SUPABASE_URL, LEADS_SUPABASE_KEY, LEADS_SUPABASE_BUCKET

API mínima (`get_storage()` retorna instância):
    .save(lead_id, filename, fileobj, mime_type) -> (storage_key, size_bytes)
    .open_stream(storage_key) -> (iterator_de_bytes, mime_type)
    .delete(storage_key) -> None

`open_stream` é usado por send_file para fazer streaming através do Flask
(simples e funciona para todos os drivers; trocar por signed URLs depois,
quando bandwidth importar).
"""
from __future__ import annotations

import os
import secrets
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Iterator


_local_uploads = Path(__file__).resolve().parent.parent / "uploads" / "leads"
UPLOAD_ROOT = _local_uploads if os.access(str(_local_uploads.parent.parent), os.W_OK) else Path("/tmp/uploads/leads")


def _safe_filename(name: str) -> str:
    # mantém extensão, troca o resto por random — evita colisão e path traversal.
    name = os.path.basename(name or "arquivo")
    base, ext = os.path.splitext(name)
    return f"{secrets.token_hex(8)}{ext.lower()}"


class Storage(ABC):
    @abstractmethod
    def save(self, lead_id: str, filename: str, fileobj: BinaryIO,
             mime_type: str | None) -> tuple[str, int]: ...

    @abstractmethod
    def open_stream(self, storage_key: str) -> Iterator[bytes]: ...

    @abstractmethod
    def delete(self, storage_key: str) -> None: ...


class LocalStorage(Storage):
    def __init__(self, root: Path = UPLOAD_ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # protege contra path traversal — só aceita keys relativos
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("storage key inválido")
        return p

    def save(self, lead_id, filename, fileobj, mime_type):
        safe = _safe_filename(filename)
        rel = f"{lead_id}/{safe}"
        target = self._path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with open(target, "wb") as out:
            while chunk := fileobj.read(64 * 1024):
                out.write(chunk)
                size += len(chunk)
        return rel, size

    def open_stream(self, storage_key):
        path = self._path(storage_key)
        def gen():
            with open(path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk
        return gen()

    def delete(self, storage_key):
        try:
            self._path(storage_key).unlink(missing_ok=True)
        except FileNotFoundError:
            pass


class S3Storage(Storage):
    def __init__(self):
        import boto3  # lazy
        self.bucket = os.environ["LEADS_S3_BUCKET"]
        self.client = boto3.client("s3", region_name=os.environ.get("LEADS_S3_REGION"))

    def save(self, lead_id, filename, fileobj, mime_type):
        safe = _safe_filename(filename)
        key = f"leads/{lead_id}/{safe}"
        # upload_fileobj usa multipart automaticamente em arquivos grandes
        extra = {"ContentType": mime_type} if mime_type else {}
        self.client.upload_fileobj(fileobj, self.bucket, key, ExtraArgs=extra)
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        return key, int(head["ContentLength"])

    def open_stream(self, storage_key):
        obj = self.client.get_object(Bucket=self.bucket, Key=storage_key)
        body = obj["Body"]
        def gen():
            for chunk in body.iter_chunks(64 * 1024):
                yield chunk
        return gen()

    def delete(self, storage_key):
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)


class SupabaseStorage(Storage):
    def __init__(self):
        from supabase import create_client  # lazy
        self.bucket = os.environ["LEADS_SUPABASE_BUCKET"]
        self.client = create_client(
            os.environ["LEADS_SUPABASE_URL"],
            os.environ["LEADS_SUPABASE_KEY"],
        )

    def save(self, lead_id, filename, fileobj, mime_type):
        safe = _safe_filename(filename)
        key = f"{lead_id}/{safe}"
        data = fileobj.read()
        opts = {"contentType": mime_type} if mime_type else {}
        self.client.storage.from_(self.bucket).upload(key, data, opts)
        return key, len(data)

    def open_stream(self, storage_key):
        data: bytes = self.client.storage.from_(self.bucket).download(storage_key)
        def gen():
            yield data
        return gen()

    def delete(self, storage_key):
        self.client.storage.from_(self.bucket).remove([storage_key])


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is not None:
        return _storage
    driver = os.environ.get("LEADS_STORAGE_DRIVER", "local").lower()
    if driver == "s3":
        _storage = S3Storage()
    elif driver == "supabase":
        _storage = SupabaseStorage()
    else:
        _storage = LocalStorage()
    return _storage
