"""Bounded versioned age container and a dual-version receiver; no extraction/network."""
import io,hashlib,stat
from zipfile import ZipFile,ZIP_DEFLATED,BadZipFile
import pyrage
from contracts.offline_bundle.v1.canonical import dumps,loads
from contracts.offline_bundle.v1.archive import encode as encode_core,decode as decode_core
from contracts.offline_bundle.v1.crypto import recipient_fingerprint
from .contract import validate
MAX_ARCHIVE=32*1024*1024
MAX_EXPANDED=48*1024*1024
MAX_COMPONENT=24*1024*1024
PATHS={'manifest':'manifest.json','extension':'h6/evidence.json','export_preview':'export/preview.json','export_authorization':'export/authorization.json'}

def encode(bundle):
    validate(bundle)
    files={path:dumps(bundle[key])+b'\n' for key,path in PATHS.items()};files['core/m0.zip']=encode_core(bundle['core'])
    if any(len(v)>MAX_COMPONENT for v in files.values()) or sum(map(len,files.values()))>MAX_EXPANDED:raise ValueError('H6 archive budget')
    files['checksums.json']=dumps({'algorithm':'SHA-256','files':{name:hashlib.sha256(value).hexdigest() for name,value in files.items()}})
    out=io.BytesIO()
    with ZipFile(out,'w',compression=ZIP_DEFLATED) as z:
        for name,value in sorted(files.items()):z.writestr(name,value)
    raw=out.getvalue()
    if len(raw)>MAX_ARCHIVE:raise ValueError('H6 archive size')
    return raw

def decode(raw):
    if len(raw)>MAX_ARCHIVE:raise ValueError('H6 archive size')
    try:
        with ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist();names=[e.filename for e in entries];expected=set(PATHS.values())|{'core/m0.zip','checksums.json'}
            if len(names)!=len(expected) or set(names)!=expected:raise ValueError('H6 archive paths')
            if sum(e.file_size for e in entries)>MAX_EXPANDED:raise ValueError('H6 expansion budget')
            files={}
            for e in entries:
                if e.flag_bits&1 or stat.S_ISLNK(e.external_attr>>16) or e.file_size>MAX_COMPONENT or e.file_size>max(1024,e.compress_size)*200:raise ValueError('H6 unsafe component')
                with z.open(e) as f:data=f.read(MAX_COMPONENT+1)
                if len(data)!=e.file_size:raise ValueError('H6 component size')
                files[e.filename]=data
        sums=loads(files.pop('checksums.json'))
        if sums!={'algorithm':'SHA-256','files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}:raise ValueError('H6 checksums')
        bundle={key:loads(files[path]) for key,path in PATHS.items()};bundle['core']=decode_core(files['core/m0.zip']);validate(bundle);return bundle
    except (BadZipFile,RuntimeError,KeyError,RecursionError,UnicodeError) as error:raise ValueError('Invalid H6 archive') from error

def encode_any(bundle):return encode(bundle) if bundle['manifest'].get('format')=='resonance-h6-bundle' else encode_core(bundle)
def decode_any(raw):
    try:
        with ZipFile(io.BytesIO(raw)) as z:h6='core/m0.zip' in z.namelist()
    except BadZipFile as error:raise ValueError('Invalid bundle archive') from error
    return decode(raw) if h6 else decode_core(raw)

def encrypt(bundle,recipient,pinned):
    if recipient_fingerprint(recipient)!=pinned or bundle['export_authorization']['recipient_fingerprint']!=pinned:raise ValueError('Recipient not pinned')
    try:return pyrage.encrypt(encode_any(bundle),[pyrage.x25519.Recipient.from_str(recipient)])
    except ValueError:raise
    except Exception as error:raise ValueError('Age encryption failed') from error

def decrypt_any(ciphertext,identity_text,pinned):
    if len(ciphertext)>MAX_ARCHIVE:raise ValueError('Ciphertext limit')
    try:
        lines=[line.strip() for line in identity_text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if len(lines)!=1:raise ValueError('One X25519 identity required')
        identity=pyrage.x25519.Identity.from_str(lines[0])
        if recipient_fingerprint(str(identity.to_public()))!=pinned:raise ValueError('Recipient not pinned')
        raw=pyrage.decrypt(ciphertext,[identity])
    except Exception as error:raise ValueError('Age authentication failed') from error
    bundle=decode_any(raw)
    if bundle['export_authorization']['recipient_fingerprint']!=pinned:raise ValueError('Recipient binding')
    return bundle
