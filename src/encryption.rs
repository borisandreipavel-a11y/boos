//! Encryption. So far only a check, made at startup, that the outside code
//! for it computes correctly on this machine. Notes: `docs/encryption.md`.

use alloc::vec::Vec;

use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use hmac::Mac;
use p256::ecdsa::signature::Verifier;
use sha2::Digest;

use crate::encryption_values::*;

// Encryption is arithmetic, and none of that arithmetic was written for this
// kernel. Before the kernel relies on it, each kind of operation is tried
// once, and its result is compared with a value worked out by something else
// (see `encryption_values.rs`). Returns how many checks came out right, and
// how many there are.
pub fn encryption_check() -> (usize, usize) {
    let checks: [fn() -> bool; 8] = [
        fingerprint_check,
        keyed_fingerprint_check,
        chacha_check,
        aes_check,
        agreement_check,
        p256_signature_check,
        p384_signature_check,
        rsa_signature_check,
    ];
    let mut right = 0;
    for check in checks {
        if check() {
            right += 1;
        }
    }
    (right, checks.len())
}

// The roots: the organisations whose signatures count. A site's certificate
// is believed if a chain of signatures leads back to one of them. This puts
// the list into the form the TLS library wants and says how many it holds.
pub fn trusted_roots() -> usize {
    let roots = rustls::RootCertStore::from_iter(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    roots.len()
}

// A fingerprint (hash) is a short number worked out from any amount of data.
// Change one bit of the data and the fingerprint comes out different.
fn fingerprint_check() -> bool {
    sha2::Sha256::digest(b"abc").as_slice() == FINGERPRINT_OF_ABC
}

// A keyed fingerprint can only be worked out by somebody who has the key.
fn keyed_fingerprint_check() -> bool {
    let Ok(mut maker) = hmac::Hmac::<sha2::Sha256>::new_from_slice(b"Jefe") else {
        return false;
    };
    maker.update(b"what do ya want for nothing?");
    maker.finalize().into_bytes().as_slice() == KEYED_FINGERPRINT
}

// Scrambling with ChaCha20-Poly1305: the example from the document that
// defines it (RFC 8439). The scrambled text ends in 16 bytes that prove
// nothing was changed on the way.
fn chacha_check() -> bool {
    let mut key = [0u8; 32];
    for (place, byte) in key.iter_mut().enumerate() {
        *byte = 0x80 + place as u8;
    }
    let number = [0x07, 0, 0, 0, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47];
    let label = [0x50, 0x51, 0x52, 0x53, 0xc0, 0xc1, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7];
    let text: &[u8] = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it.";
    let first_bytes = [0xd3, 0x1a, 0x8d, 0x34, 0x64, 0x8e, 0x60, 0xdb];
    let proof = [0x1a, 0xe1, 0x0b, 0x59, 0x4f, 0x09, 0xe2, 0x6a, 0x7e, 0x90, 0x2e, 0xcb, 0xd0, 0x60, 0x06, 0x91];

    let Ok(scrambler) = chacha20poly1305::ChaCha20Poly1305::new_from_slice(&key) else {
        return false;
    };
    let Ok(scrambled) = scrambler.encrypt(&number.into(), Payload { msg: text, aad: &label }) else {
        return false;
    };
    there_and_back(&scrambled, text, &first_bytes, &proof, |bytes| {
        scrambler.decrypt(&number.into(), Payload { msg: bytes, aad: &label }).ok()
    })
}

// Scrambling with AES-GCM: the example from the document that defines it,
// with a key, a number and a text that are all zeros.
fn aes_check() -> bool {
    let text = [0u8; 16];
    let first_bytes = [0x03, 0x88, 0xda, 0xce, 0x60, 0xb6, 0xa3, 0x92];
    let proof = [0xab, 0x6e, 0x47, 0xd4, 0x2c, 0xec, 0x13, 0xbd, 0xf5, 0x3a, 0x67, 0xb2, 0x12, 0x57, 0xbd, 0xdf];

    let Ok(scrambler) = aes_gcm::Aes128Gcm::new_from_slice(&[0u8; 16]) else {
        return false;
    };
    let Ok(scrambled) = scrambler.encrypt(&[0u8; 12].into(), Payload { msg: &text, aad: &[] }) else {
        return false;
    };
    there_and_back(&scrambled, &text, &first_bytes, &proof, |bytes| {
        scrambler.decrypt(&[0u8; 12].into(), Payload { msg: bytes, aad: &[] }).ok()
    })
}

// What both scrambling checks look at: the scrambled text begins and ends as
// the example says, unscrambling gives the text back, and after one changed
// byte the unscrambling refuses. `unscramble` is a piece of code handed in
// (a closure) that does the unscrambling.
fn there_and_back(
    scrambled: &[u8],
    text: &[u8],
    first_bytes: &[u8],
    proof: &[u8],
    unscramble: impl Fn(&[u8]) -> Option<Vec<u8>>,
) -> bool {
    if scrambled.len() != text.len() + proof.len() {
        return false;
    }
    let as_published = scrambled.starts_with(first_bytes) && scrambled.ends_with(proof);
    let comes_back = unscramble(scrambled).as_deref() == Some(text);
    let mut changed = scrambled.to_vec();
    changed[3] ^= 1;
    let change_refused = unscramble(&changed).is_none();
    as_published && comes_back && change_refused
}

// Agreeing on a secret: each side has a number of its own and shows the
// other side a point on a curve made from it. From its own number and the
// other's point, each works out the same secret, which nobody listening can.
fn agreement_check() -> bool {
    let Ok(own_number) = p256::SecretKey::from_slice(&AGREEMENT_SIDE_A) else {
        return false;
    };
    let Ok(others_point) = p256::PublicKey::from_sec1_bytes(&point(&AGREEMENT_SIDE_B_X, &AGREEMENT_SIDE_B_Y)) else {
        return false;
    };
    let secret = p256::ecdh::diffie_hellman(own_number.to_nonzero_scalar(), others_point.as_affine());
    secret.raw_secret_bytes().as_slice() == AGREEMENT_SECRET
}

// A signature proves that the holder of a key stood behind a message. It is
// checked with the public half of the key. The true signature has to be
// accepted, and the same signature on a changed message refused.
fn p256_signature_check() -> bool {
    let Ok(key) = p256::ecdsa::VerifyingKey::from_sec1_bytes(&point(&P256_KEY_X, &P256_KEY_Y)) else {
        return false;
    };
    let Ok(signature) = p256::ecdsa::Signature::from_slice(&P256_SIGNATURE) else {
        return false;
    };
    key.verify(MESSAGE, &signature).is_ok() && key.verify(&changed_message(), &signature).is_err()
}

// The same on a larger curve.
fn p384_signature_check() -> bool {
    let Ok(key) = p384::ecdsa::VerifyingKey::from_sec1_bytes(&point(&P384_KEY_X, &P384_KEY_Y)) else {
        return false;
    };
    let Ok(signature) = p384::ecdsa::Signature::from_slice(&P384_SIGNATURE) else {
        return false;
    };
    key.verify(MESSAGE, &signature).is_ok() && key.verify(&changed_message(), &signature).is_err()
}

// Signatures of the RSA sort, in its older and its newer form.
fn rsa_signature_check() -> bool {
    let Ok(first_number) = rsa::BoxedUint::from_be_slice(&RSA_KEY_N, 2048) else {
        return false;
    };
    let second_number = rsa::BoxedUint::from_be_slice_vartime(&RSA_KEY_E);
    let Ok(key) = rsa::PublicKey::new(first_number, second_number) else {
        return false;
    };

    let older = rsa::pkcs1v15::VerifyingKey::<sha2::Sha256>::new(key.clone());
    let Ok(signature) = rsa::pkcs1v15::Signature::try_from(&RSA_SIGNATURE_OLDER[..]) else {
        return false;
    };
    let older_right = older.verify(MESSAGE, &signature).is_ok() && older.verify(&changed_message(), &signature).is_err();

    let newer = rsa::pss::VerifyingKey::<sha2::Sha256>::new(key);
    let Ok(signature) = rsa::pss::Signature::try_from(&RSA_SIGNATURE_NEWER[..]) else {
        return false;
    };
    let newer_right = newer.verify(MESSAGE, &signature).is_ok() && newer.verify(&changed_message(), &signature).is_err();

    older_right && newer_right
}

// A point on a curve, written the usual way: the byte 4, then its two halves.
fn point(first_half: &[u8], second_half: &[u8]) -> Vec<u8> {
    let mut point = Vec::new();
    point.push(4);
    point.extend_from_slice(first_half);
    point.extend_from_slice(second_half);
    point
}

// The message with one bit changed.
fn changed_message() -> Vec<u8> {
    let mut changed = MESSAGE.to_vec();
    changed[0] ^= 1;
    changed
}
