//! The encrypted link (TLS). First comes the greeting, in which the site
//! proves who it is and both sides agree on keys. After it, everything that
//! travels is scrambled with those keys. Notes: `docs/encryption.md`.

use alloc::format;
use alloc::string::String;
use alloc::sync::Arc;
use alloc::vec;
use core::time::Duration;

use rustls::client::{Resumption, UnbufferedClientConnection};
use rustls::pki_types::{ServerName, UnixTime};
use rustls::time_provider::TimeProvider;
use rustls::unbuffered::{AppDataRecord, ConnectionState, EncodeError, EncryptError, UnbufferedStatus};
use rustls::{CertificateError, CipherSuite, ClientConfig, Error};

use crate::clock::{clock_read, seconds_since_1970};
use crate::encryption::{encryption_sound, root_list};
use crate::page::plain_text;
use crate::provider::provider;
use crate::random::random_number;
use crate::serial::serial_print;

// The TLS library does not send or receive anything itself. It is handed the
// bytes that arrived, and it hands back bytes to send. Whoever owns the
// connection underneath carries them, and offers these two functions.
pub trait Wire {
    // Sends all of these bytes, waiting where it has to.
    fn send(&mut self, bytes: &[u8]) -> Result<(), &'static str>;
    // Waits for bytes to arrive, puts them into `room` and says how many
    // there were. 0 means: the other side has ended the connection.
    fn receive(&mut self, room: &mut [u8]) -> Result<usize, &'static str>;
}

// Room for scrambled bytes that have arrived and are not worked through yet.
// The largest piece a site may send is a little over 16 KB.
const ARRIVED_ROOM: usize = 17 * 1024;
// Room for scrambled bytes on their way out. It grows if a piece needs more.
const OUTGOING_ROOM: usize = 2048;

// The time, as the TLS library asks for it when it checks the dates of a
// certificate: seconds since 1970, from the clock chip.
#[derive(Debug)]
struct KernelClock;

impl TimeProvider for KernelClock {
    fn current_time(&self) -> Option<UnixTime> {
        let seconds = seconds_since_1970(&clock_read()?)?;
        Some(UnixTime::since_unix_epoch(Duration::from_secs(seconds)))
    }
}

// How this kernel wants its encrypted links: the arithmetic from the
// provider, the time from the clock chip, only the newest version of TLS, the
// trusted roots, and no key of its own to show. Also says how many roots
// there are.
fn link_settings() -> Result<(Arc<ClientConfig>, usize), String> {
    let roots = root_list();
    let root_count = roots.len();
    let mut settings = ClientConfig::builder_with_details(Arc::new(provider()), Arc::new(KernelClock))
        .with_protocol_versions(&[&rustls::version::TLS13])
        .map_err(why)?
        .with_root_certificates(roots)
        .with_no_client_auth();
    // Nothing of one link is kept for the next.
    settings.resumption = Resumption::disabled();
    Ok((Arc::new(settings), root_count))
}

// Three things have to be in order before this machine can encrypt at all.
// Whoever wants an encrypted link asks this first, before sending anything.
pub fn secure_ready() -> Result<(), &'static str> {
    if !encryption_sound() {
        return Err("the check of the encryption arithmetic at startup failed");
    }
    if random_number().is_none() {
        return Err("this machine cannot make random numbers, which encryption needs");
    }
    if clock_read().and_then(|date| seconds_since_1970(&date)).is_none() {
        return Err("this machine has no usable date, which checking a certificate needs");
    }
    Ok(())
}

// One exchange over an encrypted link with the site called `name`: greet it,
// check its certificate, send `request`, and hand every piece of the answer
// to `taker`, unscrambled. Answers "true" if the site said through the link
// itself that it had sent everything, and "false" if the link simply ended.
pub fn secure_exchange(name: &str, request: &[u8], wire: &mut dyn Wire, taker: &mut dyn FnMut(&[u8])) -> Result<bool, String> {
    secure_ready()?;
    let (settings, root_count) = link_settings()?;
    let site = ServerName::try_from(String::from(name)).map_err(|_| String::from("the site's name is not a usable name"))?;
    let mut link = UnbufferedClientConnection::new(settings, site).map_err(why)?;

    let mut arrived = vec![0u8; ARRIVED_ROOM];
    let mut arrived_length = 0;
    let mut outgoing = vec![0u8; OUTGOING_ROOM];
    let mut outgoing_length = 0;
    let mut greeted = false; // The greeting is over: the site is who it says, and the keys are agreed.
    let mut announced = false;
    let mut request_sent = false;
    let mut answer_begun = false;
    let mut site_finished = false;

    loop {
        // The library works through what has arrived and says what it needs
        // next. It also says how many of the arrived bytes it is done with.
        let UnbufferedStatus { mut discard, state } = link.process_tls_records(&mut arrived[..arrived_length]);
        let mut over = false;
        match state.map_err(why)? {
            // A piece of the greeting is ready to be written out.
            ConnectionState::EncodeTlsData(mut piece) => {
                let written = match piece.encode(&mut outgoing[outgoing_length..]) {
                    Ok(written) => written,
                    Err(EncodeError::InsufficientSize(needed)) => {
                        outgoing.resize(outgoing_length + needed.required_size, 0);
                        piece.encode(&mut outgoing[outgoing_length..]).map_err(|_| String::from("a piece of the greeting could not be written"))?
                    }
                    Err(_) => return Err("a piece of the greeting could not be written".into()),
                };
                outgoing_length += written;
            }
            // What has been written out is to be sent now.
            ConnectionState::TransmitTlsData(sending) => {
                wire.send(&outgoing[..outgoing_length])?;
                outgoing_length = 0;
                sending.done();
            }
            // The greeting cannot go on before more bytes arrive.
            ConnectionState::BlockedHandshake => {
                if arrived_length == arrived.len() {
                    return Err("a piece of the site's greeting is larger than the room for it".into());
                }
                let count = wire.receive(&mut arrived[arrived_length..])?;
                if count == 0 {
                    return Err("the site ended the connection in the middle of the greeting".into());
                }
                arrived_length += count;
            }
            // The greeting is over, and data may be sent.
            ConnectionState::WriteTraffic(mut writing) => {
                greeted = true;
                if site_finished {
                    // The site has said goodbye. Say it too, and stop.
                    if let Ok(written) = writing.queue_close_notify(&mut outgoing) {
                        wire.send(&outgoing[..written]).ok();
                    }
                    over = true;
                } else if !request_sent {
                    let written = match writing.encrypt(request, &mut outgoing) {
                        Ok(written) => written,
                        Err(EncryptError::InsufficientSize(needed)) => {
                            outgoing.resize(needed.required_size, 0);
                            writing.encrypt(request, &mut outgoing).map_err(|_| String::from("the request could not be scrambled"))?
                        }
                        Err(_) => return Err("the request could not be scrambled".into()),
                    };
                    wire.send(&outgoing[..written])?;
                    request_sent = true;
                } else {
                    // The request is out. Wait for more of the answer.
                    if arrived_length == arrived.len() {
                        return Err("a piece of the site's answer is larger than the room for it".into());
                    }
                    match wire.receive(&mut arrived[arrived_length..]) {
                        // The connection ended without the site's goodbye.
                        Ok(0) => over = true,
                        Ok(count) => arrived_length += count,
                        // The wait ran out, or the connection broke. What has
                        // come of the answer is kept; it is not whole.
                        Err(_) if answer_begun => over = true,
                        Err(reason) => return Err(reason.into()),
                    }
                }
            }
            // Pieces of the answer have arrived and are unscrambled.
            ConnectionState::ReadTraffic(mut reading) => {
                while let Some(record) = reading.next_record() {
                    let AppDataRecord { discard: used, payload } = record.map_err(why)?;
                    discard += used;
                    answer_begun = true;
                    taker(payload);
                }
            }
            // The site has said, through the link, that it has sent everything.
            ConnectionState::PeerClosed => site_finished = true,
            ConnectionState::Closed => over = true,
            _ => return Err("the encrypted link took a turn this kernel does not know".into()),
        }

        // Drop the arrived bytes that the library is done with.
        if discard > 0 {
            arrived.copy_within(discard..arrived_length, 0);
            arrived_length -= discard;
        }

        if greeted && !announced {
            announced = true;
            let scrambling = match link.negotiated_cipher_suite().map(|suite| suite.suite()) {
                Some(CipherSuite::TLS13_CHACHA20_POLY1305_SHA256) => "ChaCha20-Poly1305",
                Some(CipherSuite::TLS13_AES_128_GCM_SHA256) => "AES-GCM",
                _ => "a way this kernel has no name for",
            };
            serial_print(&format!(
                "Network: {} proved who it is: its certificate leads back to one of the {} trusted roots. The link is encrypted with {}.\r\n",
                name, root_count, scrambling
            ));
        }

        if over {
            break;
        }
    }
    Ok(site_finished)
}

// Turns the TLS library's word for what went wrong into plain words. Where
// this kernel has no words of its own, the library's word follows in
// brackets, cleaned like every text that may hold bytes from outside.
fn why(error: Error) -> String {
    let words = match &error {
        Error::InvalidCertificate(trouble) => match trouble {
            CertificateError::Expired | CertificateError::ExpiredContext { .. } => "the site's certificate has run out",
            CertificateError::NotValidYet | CertificateError::NotValidYetContext { .. } => {
                "the site's certificate is not valid yet, or this machine's date is wrong"
            }
            CertificateError::UnknownIssuer => "the site's certificate does not lead back to a trusted root",
            CertificateError::NotValidForName | CertificateError::NotValidForNameContext { .. } => {
                "the site's certificate is made out to another name"
            }
            CertificateError::BadSignature => "a signature in the site's certificates is not true",
            _ => return with_library_word("the site's certificate was not accepted", &error),
        },
        Error::FailedToGetCurrentTime => "this machine has no usable date",
        Error::FailedToGetRandomBytes => "this machine cannot make random numbers",
        Error::PeerIncompatible(_) => "the site and this kernel have no way of encrypting in common",
        Error::DecryptError => "a piece from the site did not unscramble",
        Error::AlertReceived(_) => return with_library_word("the site refused the greeting", &error),
        _ => return with_library_word("the encrypted greeting failed", &error),
    };
    String::from(words)
}

fn with_library_word(words: &str, error: &Error) -> String {
    format!("{} [{}]", words, plain_text(&format!("{:?}", error), 60))
}
