"""TLS self-signed para o transporte WebSocket seguro (wss).

Firewalls corporativos com inspeção de conteúdo removem o ``Upgrade`` do
``ws://`` em claro, mas não enxergam dentro do túnel TLS: para os
intermediários, ``wss://`` é indistinguível de HTTPS na 443
(websocket.org/reference/wss-vs-ws). O certificado é gerado em memória a
cada boot do servidor (sem admin, sem domínio) e a autenticidade vem do
**pin**: o beacon de descoberta anuncia o fingerprint SHA-256 do cert e o
cliente só aceita o certificado cujo fingerprint coincida. O pin é tão
confiável quanto o beacon (descoberta não autenticada) — o TLS compra
sigilo contra inspeção passiva e atravessabilidade, não autenticação do
host.
"""

from __future__ import annotations

import hashlib
import ssl
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

__all__ = [
    "TlsMaterial",
    "client_ssl_context",
    "fingerprint_of_der",
    "generate_server_tls",
]

_CERT_LIFETIME_HOURS = 12


@dataclass(frozen=True)
class TlsMaterial:
    """Contexto TLS do servidor + fingerprint a anunciar no beacon."""

    context: ssl.SSLContext
    fingerprint: str


def _generate_cert_pem(common_name: str) -> tuple[bytes, bytes]:
    """Gera ``(key_pem, cert_pem)`` self-signed (EC P-256) em memória."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(hours=_CERT_LIFETIME_HOURS))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return key_pem, cert.public_bytes(serialization.Encoding.PEM)


def fingerprint_of_der(cert_der: bytes) -> str:
    """Fingerprint SHA-256 (hex) do certificado em formato DER."""
    return hashlib.sha256(cert_der).hexdigest()


def generate_server_tls(common_name: str = "codecon-among-us") -> TlsMaterial | None:
    """Contexto TLS do servidor + fingerprint do cert (``None`` em falha de I/O).

    Falha de geração NUNCA derruba o host: o listener sobe em ``ws://`` puro
    e o anúncio não leva fingerprint — a cascata do cliente segue em ws/tcp.
    """
    try:
        key_pem, cert_pem = _generate_cert_pem(common_name)
        # ``load_cert_chain`` exige caminhos: PEMs transitórios num diretório
        # temporário (permissões 0600 do tempfile; apagados no fim do bloco).
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "key.pem"
            cert_path = Path(tmp) / "cert.pem"
            key_path.write_bytes(key_pem)
            cert_path.write_bytes(cert_pem)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        cert_der = x509.load_pem_x509_certificate(cert_pem).public_bytes(serialization.Encoding.DER)
    except OSError:
        return None
    return TlsMaterial(context=context, fingerprint=fingerprint_of_der(cert_der))


def client_ssl_context() -> ssl.SSLContext:
    """Contexto cliente SEM validação de CA — a validação é o pin do beacon.

    ``check_hostname``/``CERT_NONE`` desligam a verificação por cadeia; o
    cliente compara o fingerprint do certificado apresentado com o anunciado
    na descoberta (pós-handshake, antes de enviar qualquer mensagem).
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
