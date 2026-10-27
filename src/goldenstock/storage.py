"""Opaque local blob keys, bounded uploads and no execution of document contents."""
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import zipfile
from fastapi import HTTPException


class FileStore:
    def __init__(self, root):
        self.root = Path(root).resolve() / 'originals'

    def path(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError('Invalid blob key')
        return path

    def write(self, key, content):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents overwriting an accepted original.
        with path.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def checksum(self, key):
        with self.path(key).open('rb') as stream:
            return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_file(filename, content, limit):
    if not content or len(content) > limit:
        raise HTTPException(413,'File is empty or exceeds the upload limit')
    if not filename or len(filename) > 200 or any(c in filename for c in '/\\\r\n\x00'):
        raise HTTPException(422,'Invalid filename')
    extension = Path(filename).suffix.lower()
    if extension == '.pdf' and content.startswith(b'%PDF-'):
        return
    if extension in {'.xlsx','.pptx'}:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos = archive.infolist()
                required = 'xl/workbook.xml' if extension == '.xlsx' else 'ppt/presentation.xml'
                names = {item.filename for item in infos}
                if len(infos)>10000 or required not in names or '[Content_Types].xml' not in names:
                    raise ValueError()
                if sum(item.file_size for item in infos)>200*1024*1024:
                    raise ValueError()
                for item in infos:
                    name = item.filename.lower()
                    if item.flag_bits & 1 or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name:
                        raise ValueError()
                    if any(x in name for x in ('vbaproject','embeddings/','externallinks/')) or name.endswith(('.exe','.dll','.js','.vbs')):
                        raise ValueError()
                    if item.file_size > max(1024*1024,item.compress_size*100):
                        raise ValueError()
                if archive.testzip() is not None:
                    raise ValueError()
            return
        except (zipfile.BadZipFile, ValueError, RuntimeError, NotImplementedError):
            raise HTTPException(422,'Unsupported, encrypted or unsafe Office archive') from None
    raise HTTPException(422,'Upload a PDF, XLSX or PPTX with a matching file signature')
