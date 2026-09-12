"""Verified cold-run archives. Active experiments and recovery ancestry are protected."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import time


def hashes(folder):
    values={}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():raise ValueError('Run archives cannot include symbolic links')
        if path.is_file():
            h=hashlib.sha256()
            with path.open('rb') as file:
                for block in iter(lambda:file.read(1024**2),b''):h.update(block)
            values[str(path.relative_to(folder))]=h.hexdigest()
    return values


def protected_runs(root):
    root=Path(root);pointer=root/'runs/active-run.json';protected=set()
    if not pointer.exists():raise ValueError('An active-run pointer is required before archiving')
    pending=[json.loads(pointer.read_text())['run_id']]
    while pending:
        key=pending.pop()
        if Path(key).name!=key:raise ValueError('Invalid run lineage')
        if key in protected:continue
        protected.add(key);path=root/'runs'/key/'manifest.json'
        if path.exists():
            m=json.loads(path.read_text())
            for field in ('recovery','migration'):
                if m.get(field,{}).get('source_run'):pending.append(m[field]['source_run'])
    return protected


def archive(root,run_id,min_age=86400,prune=False):
    root=Path(root);folder=root/'runs'/run_id
    if folder.is_symlink():raise ValueError('Run archives cannot include symbolic links')
    if Path(run_id).name!=run_id or run_id in protected_runs(root):raise ValueError('Active or ancestral recovery data cannot be archived')
    marker=next((p for p in (folder/'stopped_state.json',folder/'result.json') if p.is_file()),None)
    if not marker or time.time()-marker.stat().st_mtime<min_age:raise ValueError('Only old, explicitly stopped experiments can be archived')
    before=hashes(folder);destination=root/'archives';destination.mkdir(exist_ok=True)
    path=destination/f'{run_id}.tar.gz';index=destination/f'{run_id}.json'
    if path.exists():raise ValueError('An immutable archive already exists')
    temporary=destination/f'.{run_id}.tmp'
    try:
        with tarfile.open(temporary,'w:gz') as tar:
            for name in before:tar.add(folder/name,arcname=run_id+'/'+name,recursive=False)
        with tarfile.open(temporary,'r:gz') as tar:
            verified={}
            for member in tar:
                if not member.isfile():raise ValueError('Unexpected archive entry')
                h=hashlib.sha256();file=tar.extractfile(member)
                for block in iter(lambda:file.read(1024**2),b''):h.update(block)
                verified[str(Path(member.name).relative_to(run_id))]=h.hexdigest()
        if verified!=before or hashes(folder)!=before:raise ValueError('Archive checksum verification failed or source changed')
        with temporary.open('rb') as file:os.fsync(file.fileno())
        temporary.replace(path)
        index.write_text(json.dumps({'run_id':run_id,'created_at':time.time(),'files':before,'verified':True,
            'original_bytes':sum((folder/n).stat().st_size for n in before),'archive_bytes':path.stat().st_size},indent=2))
        with index.open('rb') as file:os.fsync(file.fileno())
        directory=os.open(destination,os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        if prune:
            if run_id in protected_runs(root) or hashes(folder)!=before:raise ValueError('Source became active or changed before removal')
            shutil.rmtree(folder)
        return json.loads(index.read_text())
    finally:
        if temporary.exists():temporary.unlink()
