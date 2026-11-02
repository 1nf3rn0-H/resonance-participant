"""age v1 X25519 transport using the pinned age-compatible Rust binding, never custom crypto."""
import hashlib
import pyrage
from .archive import encode,decode,MAX_ARCHIVE


def recipient_fingerprint(recipient):return hashlib.sha256(recipient.encode('ascii')).hexdigest()


def encrypt_bundle(bundle,recipient,pinned_fingerprint):
    fingerprint=recipient_fingerprint(recipient)
    if fingerprint!=pinned_fingerprint or bundle['export_authorization']['recipient_fingerprint']!=fingerprint:
        raise ValueError('RECIPIENT_NOT_PINNED')
    # encode validates exact preview, explicit consent and confirmation before encryption.
    plaintext=encode(bundle)
    if len(plaintext)>MAX_ARCHIVE:raise ValueError('PLAINTEXT_LIMIT')
    try:return pyrage.encrypt(plaintext,[pyrage.x25519.Recipient.from_str(recipient)])
    except Exception as error:raise ValueError('AGE_ENCRYPTION_FAILED') from error


def decrypt_bundle(ciphertext,identity_text,pinned_fingerprint):
    if len(ciphertext)>MAX_ARCHIVE:raise ValueError('CIPHERTEXT_LIMIT')
    try:
        lines=[line.strip() for line in identity_text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if len(lines)!=1:raise ValueError('Exactly one X25519 identity is required')
        identity=pyrage.x25519.Identity.from_str(lines[0])
        if recipient_fingerprint(str(identity.to_public()))!=pinned_fingerprint:raise ValueError('RECIPIENT_NOT_PINNED')
        plaintext=pyrage.decrypt(ciphertext,[identity])
    except Exception as error:raise ValueError('AGE_AUTHENTICATION_FAILED') from error
    if len(plaintext)>MAX_ARCHIVE:raise ValueError('PLAINTEXT_LIMIT')
    bundle=decode(plaintext)
    if bundle['export_authorization']['recipient_fingerprint']!=pinned_fingerprint:raise ValueError('RECIPIENT_BINDING')
    return bundle
