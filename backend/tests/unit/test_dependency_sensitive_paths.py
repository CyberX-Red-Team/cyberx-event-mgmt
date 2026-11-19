"""Code paths that depend directly on cryptography, python-jose, pypdf, Pillow
and cairosvg, and had no tests: step-ca provisioner key handling and CPE
certificate rendering. Guards dependency upgrades of those packages.
"""
import base64
import io
import json
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.keywrap import aes_key_wrap
from jose import jwt as jose_jwt
from jose.constants import Algorithms

from app.services.stepca_service import StepCAService, _decrypt_jwe_pbes2


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _encrypt_jwe_pbes2(plaintext: bytes, password: str, p2c: int = 1000) -> str:
    """Inverse of _decrypt_jwe_pbes2 (RFC 7518 PBES2-HS256+A128KW + A256GCM),
    the format step-ca uses for encrypted provisioner keys."""
    p2s = os.urandom(16)
    header_b64 = _b64u(json.dumps({
        "alg": "PBES2-HS256+A128KW", "enc": "A256GCM", "p2c": p2c, "p2s": _b64u(p2s),
    }).encode())
    kek = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=16,
        salt=b"PBES2-HS256+A128KW\x00" + p2s, iterations=p2c,
    ).derive(password.encode())
    cek = os.urandom(32)
    iv = os.urandom(12)
    sealed = AESGCM(cek).encrypt(iv, plaintext, header_b64.encode("ascii"))
    return ".".join([
        header_b64, _b64u(aes_key_wrap(kek, cek)), _b64u(iv), _b64u(sealed[:-16]), _b64u(sealed[-16:]),
    ])


def _ec_jwk(private_key) -> tuple[dict, dict]:
    nums = private_key.private_numbers()
    pub = nums.public_numbers

    def coord(n):
        return _b64u(n.to_bytes(32, "big"))

    public = {"kty": "EC", "crv": "P-256", "x": coord(pub.x), "y": coord(pub.y),
              "alg": "ES256", "kid": "test-kid", "use": "sig"}
    return {**public, "d": coord(nums.private_value)}, public


@pytest.mark.unit
class TestStepCAKeyHandling:

    def test_decrypts_step_ca_encrypted_provisioner_key(self):
        secret = json.dumps({"kty": "EC", "crv": "P-256", "d": "abc"}).encode()
        jwe = _encrypt_jwe_pbes2(secret, "provisioner-password")
        assert _decrypt_jwe_pbes2(jwe, "provisioner-password") == secret

    def test_wrong_password_fails(self):
        jwe = _encrypt_jwe_pbes2(b"secret", "right")
        with pytest.raises(Exception):
            _decrypt_jwe_pbes2(jwe, "wrong")

    def test_rejects_malformed_and_unsupported_jwe(self):
        with pytest.raises(ValueError):
            _decrypt_jwe_pbes2("a.b.c", "pw")
        bad_header = _b64u(json.dumps({"alg": "dir", "enc": "A256GCM"}).encode())
        with pytest.raises(ValueError):
            _decrypt_jwe_pbes2(f"{bad_header}.x.y.z.w", "pw")

    def test_provisioner_token_round_trip(self):
        # Mirrors StepCAService's one-time-token signing with the decrypted JWK.
        private_jwk, public_jwk = _ec_jwk(ec.generate_private_key(ec.SECP256R1()))
        claims = {"sub": "host.example.org", "sans": ["host.example.org"], "aud": "https://ca/1.0/sign"}
        token = jose_jwt.encode(claims, private_jwk, algorithm=Algorithms.ES256,
                                headers={"kid": "test-kid"})
        assert jose_jwt.get_unverified_header(token)["kid"] == "test-kid"
        decoded = jose_jwt.decode(token, public_jwk, algorithms=[Algorithms.ES256],
                                  audience="https://ca/1.0/sign")
        assert decoded["sub"] == "host.example.org"

    def test_generate_csr_and_validate_key(self):
        csr_pem, key_pem = StepCAService.generate_csr("host.example.org", ["host.example.org", "alt.example.org"])
        csr = x509.load_pem_x509_csr(csr_pem.encode() if isinstance(csr_pem, str) else csr_pem)
        assert csr.is_signature_valid
        cn = csr.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        assert cn == "host.example.org"
        key_bytes = key_pem.encode() if isinstance(key_pem, str) else key_pem
        assert StepCAService.validate_pem_private_key(key_bytes)
        with pytest.raises(ValueError):   # documented: raises on invalid input
            StepCAService.validate_pem_private_key(b"not a key")
        # The generated key matches the CSR's public key.
        key = serialization.load_pem_private_key(key_bytes, password=None)
        assert key.public_key().public_numbers() == csr.public_key().public_numbers()


@pytest.mark.unit
class TestCPECertificateRendering:

    @staticmethod
    def _base_pdf() -> bytes:
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=landscape(letter))   # 792 x 612, like the template
        c.drawString(100, 150, "Signature")
        c.drawString(500, 150, "Signature")
        c.save()
        return buf.getvalue()

    @staticmethod
    def _signature_png() -> bytes:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (300, 100), (255, 255, 255, 0))
        ImageDraw.Draw(img).line((10, 80, 290, 20), fill=(0, 0, 0, 255), width=4)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    def test_canadian_flag_renders(self):
        from PIL import Image
        from app.services.cpe_certificate_service import CPECertificateService
        flag = CPECertificateService._make_canadian_flag(width=300, height=150, alpha=40)
        img = Image.open(flag)
        assert img.size == (300, 150)
        assert img.mode == "RGBA"

    def test_signature_overlay_produces_a_valid_single_page_pdf(self):
        from pypdf import PdfReader
        from app.services.cpe_certificate_service import CPECertificateService
        out = CPECertificateService._overlay_signatures(
            self._base_pdf(), self._signature_png(), self._signature_png(),
        )
        reader = PdfReader(io.BytesIO(out))
        assert len(reader.pages) == 1
        assert round(float(reader.pages[0].mediabox.width)) == 792
        assert len(out) > len(self._base_pdf())   # overlay added content

    def test_overlay_without_signatures_still_returns_a_pdf(self):
        from pypdf import PdfReader
        from app.services.cpe_certificate_service import CPECertificateService
        out = CPECertificateService._overlay_signatures(self._base_pdf(), None, None)
        assert len(PdfReader(io.BytesIO(out)).pages) == 1
