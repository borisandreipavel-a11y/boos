//! Pictures: a picture file turned into dots, shrunk to fit a room on the
//! screen, for the kernel to paint in the frame beside the panel of apps. So
//! far it reads PNG pictures (`png.rs`), with the unpacking they need
//! (`unpack.rs`), and shrinks them (`shrink.rs`). It is code of this
//! project's own, kept in a crate of its own only so that cargo builds it to
//! run fast. Notes: `docs/pictures.md`.
//!
//! Every byte of a picture comes from outside the kernel, and may be damaged
//! or made to do harm. Nothing here may stop the kernel:
//!
//! - no unsafe code;
//! - no read outside what was given;
//! - no size taken on trust: everything that is set aside in memory is
//!   bounded first, by the limits the caller gives;
//! - no deep calls, and nothing large on the stack, which is small where the
//!   kernel runs this.
//!
//! A picture that cannot be read is turned away with the reason in plain
//! words (`Refusal`).

#![cfg_attr(not(test), no_std)]
#![forbid(unsafe_code)]
// These would let a damaged file stop the kernel. `cargo clippy` turns any
// use of them into an error (see test-tools/test_pictures.py).
#![deny(
    clippy::indexing_slicing,
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::unreachable,
    clippy::todo,
    clippy::unimplemented,
    clippy::get_unwrap
)]

extern crate alloc;

mod check;
mod png;
mod shrink;
mod unpack;

#[cfg(test)]
mod tests;

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

pub use png::{PngHead, png_head, png_picture};
pub use shrink::fitted_size;

/// How large a picture may be. The caller sets these, since only it knows how
/// much memory it can give. Every piece of memory set aside for a picture is
/// bounded by them, or by the room, before it is set aside.
#[derive(Clone, Copy, Debug)]
pub struct Limits {
    /// The most dots a picture may have, its width times its height.
    pub dots_most: u64,
    /// The most dots on either side.
    pub side_most: u32,
    /// The most dots an interlaced picture may have. Such a picture comes in
    /// seven passes over the whole of it, so it is put together whole, four
    /// bytes a dot, before it is shrunk.
    pub interlaced_dots_most: u64,
}

/// A picture as dots, ready to paint: `width` times `height` dots, row after
/// row from the top, four bytes each: red, green, blue, and how much the dot
/// covers what lies behind it (alpha: 0 not at all, 255 wholly). The colours
/// are not mixed with any background, so that the kernel can paint the same
/// dots over another look's colour without reading the file again.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Picture {
    pub width: u32,
    pub height: u32,
    pub dots: Vec<u8>,
}

/// Why a picture was not read.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// It does not begin as a PNG picture does.
    NotPng,
    /// The file ends before the picture does.
    CutShort,
    /// Something in it is not as its format allows; the words say what.
    Damaged(&'static str),
    /// It holds a part that a reader must understand to show it, and this
    /// one does not know it. The part's four-letter name.
    UnknownPart([u8; 4]),
    /// It has more dots than the limits allow: its width and height.
    TooLarge { width: u32, height: u32 },
    /// The room given has no dots.
    NoRoom,
}

impl Refusal {
    /// The reason in plain words, to stand after "because": "the file ends
    /// before the picture does".
    pub fn because(&self) -> String {
        match self {
            Refusal::NotPng => String::from("it does not begin as a PNG picture does"),
            Refusal::CutShort => String::from("the file ends before the picture does"),
            Refusal::Damaged(what) => format!("it is damaged: {}", what),
            Refusal::UnknownPart(name) => {
                let shown: String = name.iter().map(|byte| if byte.is_ascii_alphabetic() { *byte as char } else { '.' }).collect();
                format!("it holds a part I cannot read, \"{}\"", shown)
            }
            Refusal::TooLarge { width, height } => format!("it is {} by {} dots, more than I show", width, height),
            Refusal::NoRoom => String::from("there is no room to show it"),
        }
    }
}
