"""SSH key generation utility."""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def generate_ssh_keypair() -> tuple[str, str]:
    """
    Generate an ECDSA (P-256) SSH key pair.

    Returns:
        tuple: (public_key_str, private_key_str)
    """
    key = ec.generate_private_key(ec.SECP256R1())

    # Get private key in OpenSSH format
    private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption()
    ).decode('utf-8')

    # Get public key in OpenSSH format
    public_key = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH
    ).decode('utf-8')

    # Add comment to public key
    public_key_with_comment = f"{public_key} cyberx-event"

    return public_key_with_comment, private_key
