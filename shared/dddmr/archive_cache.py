"""Validate complete upstream source archives before adding them to build contexts."""
import gzip
import hashlib
import json
import shutil
import tarfile
from pathlib import Path


def stage_archive(work: Path, context: Path, name: str, expected_commit=None, expected_sha256=None):
    archive = work / 'downloads' / name
    if not archive.is_file():
        raise FileNotFoundError(f'Missing complete source archive: {archive}')
    try:
        with gzip.open(archive, 'rb') as stream:
            while stream.read(1024 * 1024):
                pass
        with tarfile.open(archive, 'r:gz') as source:
            members = source.getmembers()
            commit = source.pax_headers.get('comment')
            roots = {Path(m.name).parts[0] for m in members if m.name}
            if not members or len(roots) != 1:
                raise ValueError('Expected one source directory in archive.')
            for member in members:
                p = Path(member.name)
                if p.is_absolute() or '..' in p.parts:
                    raise ValueError(f'Invalid archive path: {member.name}')
            if expected_commit and commit != expected_commit:
                raise ValueError(f'Archive commit mismatch: {commit}')
    except (EOFError, OSError, tarfile.TarError) as exc:
        raise RuntimeError(f'Archive download incomplete or corrupt: {archive}') from exc
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError(f'Archive SHA256 mismatch: {archive}')
    info = {'file': name, 'bytes': archive.stat().st_size, 'sha256': digest,
            'git_commit': commit, 'entries': len(members), 'source_root': next(iter(roots))}
    archive.with_name(name + '.verified.json').write_text(json.dumps(info, indent=2) + '\n')
    target = context / 'sources' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(archive, target)
    print(f'Validated {name}: {info["bytes"]} bytes, {len(members)} entries', flush=True)
    return info
