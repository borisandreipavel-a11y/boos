//! The provider: the adapter between rustls, which speaks TLS but does no
//! arithmetic, and the crates that do the arithmetic. Each piece here says
//! "when rustls asks for this, call that". Notes: `docs/encryption.md`.

use alloc::boxed::Box;
use alloc::sync::Arc;
use alloc::vec;
use alloc::vec::Vec;
use core::marker::PhantomData;

use chacha20poly1305::aead::{AeadInOut, KeyInit, Nonce as ScramblerNumber, Tag as ScramblerProof};
use der::{Decode, Reader};
use hmac::Mac;
use p256::ecdsa::signature::Verifier;
use p256::ecdsa::signature::hazmat::PrehashVerifier;
use p256::elliptic_curve::sec1::ToSec1Point;
use rustls::crypto::cipher::{
    AeadKey, InboundOpaqueMessage, InboundPlainMessage, Iv, MessageDecrypter, MessageEncrypter, Nonce,
    OutboundOpaqueMessage, OutboundPlainMessage, PrefixedPayload, Tls13AeadAlgorithm, UnsupportedOperationError,
    make_tls13_aad,
};
use rustls::crypto::tls13::HkdfUsingHmac;
use rustls::crypto::{
    ActiveKeyExchange, CryptoProvider, GetRandomFailed, KeyProvider, SecureRandom, SharedSecret, SupportedKxGroup,
    WebPkiSupportedAlgorithms, hash, hmac as keyed,
};
use rustls::pki_types::{AlgorithmIdentifier, InvalidSignature, PrivateKeyDer, SignatureVerificationAlgorithm, alg_id};
use rustls::sign::SigningKey;
use rustls::{
    CipherSuite, CipherSuiteCommon, ConnectionTrafficSecrets, ContentType, Error, NamedGroup, PeerMisbehaved,
    ProtocolVersion, SignatureScheme, SupportedCipherSuite, Tls13CipherSuite,
};
use sha2::Digest;

use crate::random::random_fill;

// Everything rustls needs from outside, in one value.
pub fn provider() -> CryptoProvider {
    CryptoProvider {
        // The ways of scrambling this kernel offers a site, the preferred one
        // first. Every site that speaks TLS 1.3 knows the second.
        cipher_suites: vec![SupportedCipherSuite::Tls13(&CHACHA_SUITE), SupportedCipherSuite::Tls13(&AES_SUITE)],
        // The one way of agreeing on a secret key.
        kx_groups: vec![&P256Agreement],
        signature_verification_algorithms: SIGNATURE_CHECKS,
        secure_random: &KernelRandom,
        key_provider: &NoOwnKey,
    }
}

// ---------- Fingerprints ----------

// SHA-256, as rustls wants it: for a whole piece of data at once, or fed
// piece by piece.
struct Fingerprint;

impl hash::Hash for Fingerprint {
    fn start(&self) -> Box<dyn hash::Context> {
        Box::new(FingerprintUnderWay(sha2::Sha256::new()))
    }

    fn hash(&self, data: &[u8]) -> hash::Output {
        hash::Output::new(&sha2::Sha256::digest(data))
    }

    fn output_len(&self) -> usize {
        32
    }

    fn algorithm(&self) -> hash::HashAlgorithm {
        hash::HashAlgorithm::SHA256
    }
}

struct FingerprintUnderWay(sha2::Sha256);

impl hash::Context for FingerprintUnderWay {
    // The fingerprint of what was fed so far, while the feeding can go on.
    fn fork_finish(&self) -> hash::Output {
        hash::Output::new(&self.0.clone().finalize())
    }

    fn fork(&self) -> Box<dyn hash::Context> {
        Box::new(FingerprintUnderWay(self.0.clone()))
    }

    fn finish(self: Box<Self>) -> hash::Output {
        hash::Output::new(&self.0.finalize())
    }

    fn update(&mut self, data: &[u8]) {
        self.0.update(data);
    }
}

// The keyed fingerprint (HMAC-SHA256). rustls makes all the keys of a
// connection out of it.
struct KeyedFingerprint;

impl keyed::Hmac for KeyedFingerprint {
    fn with_key(&self, key: &[u8]) -> Box<dyn keyed::Key> {
        // A key of any length is taken, so this cannot fail.
        Box::new(KeyedFingerprintWithKey(hmac::Hmac::<sha2::Sha256>::new_from_slice(key).expect("a key of any length is taken")))
    }

    fn hash_output_len(&self) -> usize {
        32
    }
}

struct KeyedFingerprintWithKey(hmac::Hmac<sha2::Sha256>);

impl keyed::Key for KeyedFingerprintWithKey {
    fn sign_concat(&self, first: &[u8], middle: &[&[u8]], last: &[u8]) -> keyed::Tag {
        let mut maker = self.0.clone();
        maker.update(first);
        for piece in middle {
            maker.update(piece);
        }
        maker.update(last);
        keyed::Tag::new(&maker.finalize().into_bytes())
    }

    fn tag_len(&self) -> usize {
        32
    }
}

// ---------- Scrambling ----------

// The two ways of scrambling. Each is a set: the scrambling itself, the
// fingerprint that goes with it, and the making of keys.
static CHACHA_SUITE: Tls13CipherSuite = Tls13CipherSuite {
    common: CipherSuiteCommon {
        suite: CipherSuite::TLS13_CHACHA20_POLY1305_SHA256,
        hash_provider: &Fingerprint,
        // How many pieces may be scrambled with one key. No limit that a
        // connection could reach.
        confidentiality_limit: u64::MAX,
    },
    hkdf_provider: &HkdfUsingHmac(&KeyedFingerprint),
    aead_alg: &Scrambling::<chacha20poly1305::ChaCha20Poly1305>(PhantomData),
    quic: None,
};

static AES_SUITE: Tls13CipherSuite = Tls13CipherSuite {
    common: CipherSuiteCommon {
        suite: CipherSuite::TLS13_AES_128_GCM_SHA256,
        hash_provider: &Fingerprint,
        // With AES-GCM a key must be replaced after about 16 million pieces.
        confidentiality_limit: 1 << 24,
    },
    hkdf_provider: &HkdfUsingHmac(&KeyedFingerprint),
    aead_alg: &Scrambling::<aes_gcm::Aes128Gcm>(PhantomData),
    quic: None,
};

// How long the proof is that both ways of scrambling put behind each piece.
const PROOF_LENGTH: usize = 16;

// One way of scrambling. The `C` stands for the outside type that does it:
// the code below is written once and serves both. `PhantomData` only carries
// that type along; it holds no data.
struct Scrambling<C>(PhantomData<C>);

// A way of scrambling with its key set: ready to scramble or unscramble the
// pieces of one direction of a connection.
struct ScramblingWithKey<C> {
    scrambler: C,
    start_number: Iv,
}

impl<C> Tls13AeadAlgorithm for Scrambling<C>
where
    C: AeadInOut + KeyInit + Send + Sync + 'static,
{
    fn encrypter(&self, key: AeadKey, start_number: Iv) -> Box<dyn MessageEncrypter> {
        Box::new(ScramblingWithKey::<C>::new(key, start_number))
    }

    fn decrypter(&self, key: AeadKey, start_number: Iv) -> Box<dyn MessageDecrypter> {
        Box::new(ScramblingWithKey::<C>::new(key, start_number))
    }

    fn key_len(&self) -> usize {
        C::key_size()
    }

    // Handing the keys out to somebody else is not offered.
    fn extract_keys(&self, _key: AeadKey, _start_number: Iv) -> Result<ConnectionTrafficSecrets, UnsupportedOperationError> {
        Err(UnsupportedOperationError)
    }
}

impl<C: KeyInit> ScramblingWithKey<C> {
    fn new(key: AeadKey, start_number: Iv) -> ScramblingWithKey<C> {
        // rustls hands over a key of exactly the length asked for in `key_len`.
        ScramblingWithKey { scrambler: C::new_from_slice(key.as_ref()).expect("the key has the length asked for"), start_number }
    }
}

impl<C> MessageEncrypter for ScramblingWithKey<C>
where
    C: AeadInOut + Send + Sync,
{
    // Scrambles one piece. `count` is the piece's number on this connection;
    // it goes into the scrambling, so that no two pieces are scrambled alike.
    fn encrypt(&mut self, piece: OutboundPlainMessage<'_>, count: u64) -> Result<OutboundOpaqueMessage, Error> {
        let whole_length = self.encrypted_payload_len(piece.payload.len());
        let mut bytes = PrefixedPayload::with_capacity(whole_length);
        bytes.extend_from_chunks(&piece.payload);
        // The kind of the piece travels scrambled too, as one more byte.
        bytes.extend_from_slice(&[u8::from(piece.typ)]);

        let number = ScramblerNumber::<C>::try_from(&Nonce::new(&self.start_number, count).0[..]).map_err(|_| Error::EncryptError)?;
        let label = make_tls13_aad(whole_length);
        let proof = self
            .scrambler
            .encrypt_inout_detached(&number, &label, bytes.as_mut().into())
            .map_err(|_| Error::EncryptError)?;
        bytes.extend_from_slice(&proof);

        Ok(OutboundOpaqueMessage::new(ContentType::ApplicationData, ProtocolVersion::TLSv1_2, bytes))
    }

    fn encrypted_payload_len(&self, payload_len: usize) -> usize {
        payload_len + 1 + PROOF_LENGTH
    }
}

impl<C> MessageDecrypter for ScramblingWithKey<C>
where
    C: AeadInOut + Send + Sync,
{
    // Unscrambles one piece, after checking its proof. A piece that was
    // changed on the way is refused.
    fn decrypt<'a>(&mut self, mut piece: InboundOpaqueMessage<'a>, count: u64) -> Result<InboundPlainMessage<'a>, Error> {
        let bytes = &mut piece.payload;
        if bytes.len() < PROOF_LENGTH {
            return Err(Error::DecryptError);
        }
        let number = ScramblerNumber::<C>::try_from(&Nonce::new(&self.start_number, count).0[..]).map_err(|_| Error::DecryptError)?;
        let label = make_tls13_aad(bytes.len());
        let text_length = bytes.len() - PROOF_LENGTH;
        let (text, proof) = bytes.split_at_mut(text_length);
        let proof = ScramblerProof::<C>::try_from(&proof[..]).map_err(|_| Error::DecryptError)?;
        self.scrambler
            .decrypt_inout_detached(&number, &label, text.into(), &proof)
            .map_err(|_| Error::DecryptError)?;
        bytes.truncate(text_length);
        piece.into_tls13_unpadded_message()
    }
}

// ---------- Agreeing on a secret key ----------

// On the curve P-256: this side makes a number of its own at random and shows
// the site a point made from it. From its own number and the site's point it
// works out the secret, which nobody listening can.
#[derive(Debug)]
struct P256Agreement;

struct P256AgreementUnderWay {
    own_number: p256::SecretKey,
    shown_point: Vec<u8>,
}

impl SupportedKxGroup for P256Agreement {
    fn start(&self) -> Result<Box<dyn ActiveKeyExchange>, Error> {
        // 32 random bytes are a usable number in all but one case in four
        // thousand million. Try a few times all the same.
        for _ in 0..8 {
            let mut bytes = [0u8; 32];
            if !random_fill(&mut bytes) {
                return Err(Error::FailedToGetRandomBytes);
            }
            if let Ok(own_number) = p256::SecretKey::from_slice(&bytes) {
                let shown_point = own_number.public_key().to_sec1_point(false).as_bytes().to_vec();
                return Ok(Box::new(P256AgreementUnderWay { own_number, shown_point }));
            }
        }
        Err(Error::FailedToGetRandomBytes)
    }

    fn name(&self) -> NamedGroup {
        NamedGroup::secp256r1
    }
}

impl ActiveKeyExchange for P256AgreementUnderWay {
    fn complete(self: Box<Self>, others_point: &[u8]) -> Result<SharedSecret, Error> {
        // A point that does not lie on the curve is refused here.
        let others_point = p256::PublicKey::from_sec1_bytes(others_point).map_err(|_| Error::PeerMisbehaved(PeerMisbehaved::InvalidKeyShare))?;
        let secret = p256::ecdh::diffie_hellman(self.own_number.to_nonzero_scalar(), others_point.as_affine());
        Ok(SharedSecret::from(secret.raw_secret_bytes().as_slice()))
    }

    fn pub_key(&self) -> &[u8] {
        &self.shown_point
    }

    fn group(&self) -> NamedGroup {
        NamedGroup::secp256r1
    }
}

// ---------- Checking signatures ----------

// This is how a certificate is checked: every certificate in the chain
// carries a signature made by the next one up. rustls's certificate checker
// asks here whether a signature is true. There are two sorts, on a curve and
// RSA, and each comes with a choice of fingerprint.
#[derive(Debug, Clone, Copy)]
enum Curve {
    P256,
    P384,
}

#[derive(Debug, Clone, Copy)]
enum FingerprintKind {
    Sha256,
    Sha384,
    Sha512,
}

#[derive(Debug, Clone, Copy)]
enum RsaForm {
    Older, // PKCS#1 v1.5
    Newer, // PSS
}

#[derive(Debug)]
struct CurveSignature {
    curve: Curve,
    fingerprint: FingerprintKind,
}

#[derive(Debug)]
struct RsaSignature {
    form: RsaForm,
    fingerprint: FingerprintKind,
}

// A key of the RSA sort has to be at least 2048 bits long to be trusted
// today, and none longer than 8192 bits is taken.
const RSA_SHORTEST: usize = 2048 / 8;
const RSA_LONGEST: usize = 8192 / 8;

impl SignatureVerificationAlgorithm for CurveSignature {
    fn verify_signature(&self, public_key: &[u8], message: &[u8], signature: &[u8]) -> Result<(), InvalidSignature> {
        // The signature is two numbers. The check is made on the message's fingerprint.
        let (first, second) = two_numbers(signature).ok_or(InvalidSignature)?;
        let print = fingerprint_of(message, self.fingerprint);
        match self.curve {
            Curve::P256 => {
                let key = p256::ecdsa::VerifyingKey::from_sec1_bytes(public_key).map_err(|_| InvalidSignature)?;
                let signature = p256::ecdsa::Signature::from_scalars(widened::<32>(first)?, widened::<32>(second)?).map_err(|_| InvalidSignature)?;
                key.verify_prehash(&print, &signature).map_err(|_| InvalidSignature)
            }
            Curve::P384 => {
                let key = p384::ecdsa::VerifyingKey::from_sec1_bytes(public_key).map_err(|_| InvalidSignature)?;
                let signature = p384::ecdsa::Signature::from_scalars(widened::<48>(first)?, widened::<48>(second)?).map_err(|_| InvalidSignature)?;
                key.verify_prehash(&print, &signature).map_err(|_| InvalidSignature)
            }
        }
    }

    // The two labels by which a certificate names the sort of key and the
    // sort of signature. The checker picks the piece here whose labels match.
    fn public_key_alg_id(&self) -> AlgorithmIdentifier {
        match self.curve {
            Curve::P256 => alg_id::ECDSA_P256,
            Curve::P384 => alg_id::ECDSA_P384,
        }
    }

    fn signature_alg_id(&self) -> AlgorithmIdentifier {
        match self.fingerprint {
            FingerprintKind::Sha256 => alg_id::ECDSA_SHA256,
            FingerprintKind::Sha384 => alg_id::ECDSA_SHA384,
            FingerprintKind::Sha512 => alg_id::ECDSA_SHA512,
        }
    }
}

impl SignatureVerificationAlgorithm for RsaSignature {
    fn verify_signature(&self, public_key: &[u8], message: &[u8], signature: &[u8]) -> Result<(), InvalidSignature> {
        // The public half of an RSA key is two numbers.
        let (first, second) = two_numbers(public_key).ok_or(InvalidSignature)?;
        if first.len() < RSA_SHORTEST || first.len() > RSA_LONGEST {
            return Err(InvalidSignature);
        }
        let key = rsa::PublicKey::new(rsa::BoxedUint::from_be_slice_vartime(first), rsa::BoxedUint::from_be_slice_vartime(second))
            .map_err(|_| InvalidSignature)?;
        let right = match (self.form, self.fingerprint) {
            (RsaForm::Older, FingerprintKind::Sha256) => rsa_older_is_true::<sha2::Sha256>(key, message, signature),
            (RsaForm::Older, FingerprintKind::Sha384) => rsa_older_is_true::<sha2::Sha384>(key, message, signature),
            (RsaForm::Older, FingerprintKind::Sha512) => rsa_older_is_true::<sha2::Sha512>(key, message, signature),
            (RsaForm::Newer, FingerprintKind::Sha256) => rsa_newer_is_true::<sha2::Sha256>(key, message, signature),
            (RsaForm::Newer, FingerprintKind::Sha384) => rsa_newer_is_true::<sha2::Sha384>(key, message, signature),
            (RsaForm::Newer, FingerprintKind::Sha512) => rsa_newer_is_true::<sha2::Sha512>(key, message, signature),
        };
        if right { Ok(()) } else { Err(InvalidSignature) }
    }

    fn public_key_alg_id(&self) -> AlgorithmIdentifier {
        alg_id::RSA_ENCRYPTION
    }

    fn signature_alg_id(&self) -> AlgorithmIdentifier {
        match (self.form, self.fingerprint) {
            (RsaForm::Older, FingerprintKind::Sha256) => alg_id::RSA_PKCS1_SHA256,
            (RsaForm::Older, FingerprintKind::Sha384) => alg_id::RSA_PKCS1_SHA384,
            (RsaForm::Older, FingerprintKind::Sha512) => alg_id::RSA_PKCS1_SHA512,
            (RsaForm::Newer, FingerprintKind::Sha256) => alg_id::RSA_PSS_SHA256,
            (RsaForm::Newer, FingerprintKind::Sha384) => alg_id::RSA_PSS_SHA384,
            (RsaForm::Newer, FingerprintKind::Sha512) => alg_id::RSA_PSS_SHA512,
        }
    }
}

// The `D` stands for the fingerprint to use; the lines after `where` say what
// the outside code demands of it.
fn rsa_older_is_true<D>(key: rsa::PublicKey, message: &[u8], signature: &[u8]) -> bool
where
    D: Digest + sha2::digest::const_oid::AssociatedOid,
{
    match rsa::pkcs1v15::Signature::try_from(signature) {
        Ok(signature) => rsa::pkcs1v15::VerifyingKey::<D>::new(key).verify(message, &signature).is_ok(),
        Err(_) => false,
    }
}

fn rsa_newer_is_true<D>(key: rsa::PublicKey, message: &[u8], signature: &[u8]) -> bool
where
    D: Digest + sha2::digest::FixedOutputReset,
{
    match rsa::pss::Signature::try_from(signature) {
        Ok(signature) => rsa::pss::VerifyingKey::<D>::new(key).verify(message, &signature).is_ok(),
        Err(_) => false,
    }
}

fn fingerprint_of(message: &[u8], kind: FingerprintKind) -> Vec<u8> {
    match kind {
        FingerprintKind::Sha256 => sha2::Sha256::digest(message).to_vec(),
        FingerprintKind::Sha384 => sha2::Sha384::digest(message).to_vec(),
        FingerprintKind::Sha512 => sha2::Sha512::digest(message).to_vec(),
    }
}

// Certificates write a pair of numbers in a fixed form: a wrapper, then each
// number with its length in front (DER). This takes the pair apart. Anything
// else in those bytes, such as bytes after the pair, makes it answer "nothing".
fn two_numbers(encoded: &[u8]) -> Option<(&[u8], &[u8])> {
    let mut reader = der::SliceReader::new(encoded).ok()?;
    let pair = reader
        .sequence(|inside| {
            let first = der::asn1::UintRef::decode(inside)?;
            let second = der::asn1::UintRef::decode(inside)?;
            Ok::<_, der::Error>((first.as_bytes(), second.as_bytes()))
        })
        .ok()?;
    // Nothing may follow the pair.
    reader.finish().ok()?;
    Some(pair)
}

// Writes a number into exactly `N` bytes, with zeros in front. A number that
// is too long for that is refused.
fn widened<const N: usize>(number: &[u8]) -> Result<[u8; N], InvalidSignature> {
    if number.len() > N {
        return Err(InvalidSignature);
    }
    let mut wide = [0u8; N];
    wide[N - number.len()..].copy_from_slice(number);
    Ok(wide)
}

static P256_SHA256: CurveSignature = CurveSignature { curve: Curve::P256, fingerprint: FingerprintKind::Sha256 };
static P256_SHA384: CurveSignature = CurveSignature { curve: Curve::P256, fingerprint: FingerprintKind::Sha384 };
static P384_SHA256: CurveSignature = CurveSignature { curve: Curve::P384, fingerprint: FingerprintKind::Sha256 };
static P384_SHA384: CurveSignature = CurveSignature { curve: Curve::P384, fingerprint: FingerprintKind::Sha384 };
static RSA_OLDER_SHA256: RsaSignature = RsaSignature { form: RsaForm::Older, fingerprint: FingerprintKind::Sha256 };
static RSA_OLDER_SHA384: RsaSignature = RsaSignature { form: RsaForm::Older, fingerprint: FingerprintKind::Sha384 };
static RSA_OLDER_SHA512: RsaSignature = RsaSignature { form: RsaForm::Older, fingerprint: FingerprintKind::Sha512 };
static RSA_NEWER_SHA256: RsaSignature = RsaSignature { form: RsaForm::Newer, fingerprint: FingerprintKind::Sha256 };
static RSA_NEWER_SHA384: RsaSignature = RsaSignature { form: RsaForm::Newer, fingerprint: FingerprintKind::Sha384 };
static RSA_NEWER_SHA512: RsaSignature = RsaSignature { form: RsaForm::Newer, fingerprint: FingerprintKind::Sha512 };

// The whole list, and which pieces serve which kind of signature that a site
// may use in the greeting itself.
static SIGNATURE_CHECKS: WebPkiSupportedAlgorithms = WebPkiSupportedAlgorithms {
    all: &[
        &P256_SHA256,
        &P256_SHA384,
        &P384_SHA256,
        &P384_SHA384,
        &RSA_OLDER_SHA256,
        &RSA_OLDER_SHA384,
        &RSA_OLDER_SHA512,
        &RSA_NEWER_SHA256,
        &RSA_NEWER_SHA384,
        &RSA_NEWER_SHA512,
    ],
    mapping: &[
        (SignatureScheme::ECDSA_NISTP384_SHA384, &[&P384_SHA384, &P256_SHA384]),
        (SignatureScheme::ECDSA_NISTP256_SHA256, &[&P256_SHA256, &P384_SHA256]),
        (SignatureScheme::RSA_PSS_SHA512, &[&RSA_NEWER_SHA512]),
        (SignatureScheme::RSA_PSS_SHA384, &[&RSA_NEWER_SHA384]),
        (SignatureScheme::RSA_PSS_SHA256, &[&RSA_NEWER_SHA256]),
        (SignatureScheme::RSA_PKCS1_SHA512, &[&RSA_OLDER_SHA512]),
        (SignatureScheme::RSA_PKCS1_SHA384, &[&RSA_OLDER_SHA384]),
        (SignatureScheme::RSA_PKCS1_SHA256, &[&RSA_OLDER_SHA256]),
    ],
};

// ---------- Random numbers, and a key of this kernel's own ----------

// rustls takes its random bytes from the kernel's own source. Without a
// source it gets a "no", and no connection is made.
#[derive(Debug)]
struct KernelRandom;

impl SecureRandom for KernelRandom {
    fn fill(&self, bytes: &mut [u8]) -> Result<(), GetRandomFailed> {
        if random_fill(bytes) { Ok(()) } else { Err(GetRandomFailed) }
    }
}

// A site could ask this side to prove who it is with a key of its own. This
// kernel has none.
#[derive(Debug)]
struct NoOwnKey;

impl KeyProvider for NoOwnKey {
    fn load_private_key(&self, _key: PrivateKeyDer<'static>) -> Result<Arc<dyn SigningKey>, Error> {
        Err(Error::General("this kernel has no key of its own".into()))
    }
}
