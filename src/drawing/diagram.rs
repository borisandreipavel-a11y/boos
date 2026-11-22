//! Bounded rectangles, lines, arrows and labels in the drawing frame.

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;
use core::str::SplitAsciiWhitespace;

use super::{FRAME, PADDING, Place, SIGN, TEXT_SIZE, TABLE_TEXT_MOST, paint_frame, read_colour, readable};
use crate::letters::LETTER_HEIGHT;
use crate::look::look;
use crate::screen::{Colour, screen_rectangle, screen_text};

pub(super) const SHAPES_MOST: usize = 48;
const STROKE: u32 = 2;

#[derive(Clone, Copy, PartialEq, Eq)]
struct Point {
    x: u32,
    y: u32,
}

enum Shape {
    Rectangle(Point, u32, u32),
    Line(Point, Point),
    Arrow(Point, Point),
    Text(Point, String),
}

pub(super) struct Diagram {
    source: String,
    shapes: Vec<(Option<Colour>, Shape)>,
}

pub(super) fn room(place: &Place) -> (u32, u32) {
    (place.inside_width(), place.height - 2 * (FRAME + PADDING))
}

pub(super) fn read(text: &str, room: (u32, u32)) -> Result<Diagram, String> {
    if text.len() > TABLE_TEXT_MOST {
        return Err(String::from("the diagram description was too long."));
    }
    let mut shapes = Vec::new();
    let mut ink = None;
    for (index, line) in text.lines().enumerate() {
        let mut words = line.split_ascii_whitespace();
        let Some(command) = words.next() else { continue };
        let row = index + 1;
        if command == "ink" {
            ink = match (words.next(), words.next()) {
                (Some("default"), None) => None,
                (Some(hex), None) => Some(read_colour(hex).ok_or_else(|| format!("diagram line {} needs a colour like #0066aa.", row))?),
                _ => return Err(format!("diagram line {} needs one ink colour or default.", row)),
            };
            continue;
        }
        let shape = shape(command, &mut words, room)
            .ok_or_else(|| format!("diagram line {} has invalid inputs or goes outside the frame.", row))?;
        if shapes.len() == SHAPES_MOST {
            return Err(format!("a diagram can have at most {} shapes.", SHAPES_MOST));
        }
        shapes.push((ink, shape));
    }
    if shapes.is_empty() {
        return Err(String::from("the diagram had no shapes to draw."));
    }
    Ok(Diagram { source: String::from(text), shapes })
}

fn number(words: &mut SplitAsciiWhitespace<'_>) -> Option<u32> {
    let text = words.next()?;
    if !text.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    text.parse().ok()
}

fn point(words: &mut SplitAsciiWhitespace<'_>, (width, height): (u32, u32)) -> Option<Point> {
    let point = Point { x: number(words)?, y: number(words)? };
    (point.x < width && point.y < height).then_some(point)
}

fn shape(command: &str, words: &mut SplitAsciiWhitespace<'_>, bounds: (u32, u32)) -> Option<Shape> {
    let start = point(words, bounds)?;
    let shape = match command {
        "rect" => {
            let (width, height) = (number(words)?, number(words)?);
            if width == 0 || height == 0 || width > bounds.0 - start.x || height > bounds.1 - start.y {
                return None;
            }
            Shape::Rectangle(start, width, height)
        }
        "line" => Shape::Line(start, point(words, bounds)?),
        "arrow" => {
            let end = point(words, bounds)?;
            if start == end {
                return None;
            }
            Shape::Arrow(start, end)
        }
        "text" => {
            let text = words.collect::<Vec<_>>().join(" ");
            if text.is_empty() || !text.bytes().all(|byte| (b' '..=b'~').contains(&byte)) ||
                text.len() > ((bounds.0 - start.x) / SIGN) as usize ||
                TEXT_SIZE * LETTER_HEIGHT > bounds.1 - start.y
            {
                return None;
            }
            return Some(Shape::Text(start, text));
        }
        _ => return None,
    };
    words.next().is_none().then_some(shape)
}

impl Diagram {
    pub(super) fn source(&self) -> &str {
        &self.source
    }

    pub(super) fn paint(&self, place: &Place) {
        let look = look();
        paint_frame(place);
        let area = Area {
            left: place.left + FRAME + PADDING,
            top: place.top + FRAME + PADDING,
            bounds: room(place),
        };
        for (requested, shape) in &self.shapes {
            let ink = readable(requested.unwrap_or(look.panel_text), look.panel_inside);
            match shape {
                Shape::Rectangle(start, width, height) => area.outline(*start, *width, *height, ink),
                Shape::Line(start, end) => area.line(*start, *end, ink),
                Shape::Arrow(start, end) => area.arrow(*start, *end, ink),
                Shape::Text(start, text) => screen_text(area.left + start.x, area.top + start.y, text, TEXT_SIZE, ink),
            }
        }
    }
}

struct Area {
    left: u32,
    top: u32,
    bounds: (u32, u32),
}

impl Area {
    fn outline(&self, at: Point, width: u32, height: u32, ink: Colour) {
        let (left, top) = (self.left + at.x, self.top + at.y);
        let (side, edge) = (STROKE.min(width), STROKE.min(height));
        screen_rectangle(left, top, width, edge, ink);
        screen_rectangle(left, top + height - edge, width, edge, ink);
        screen_rectangle(left, top, side, height, ink);
        screen_rectangle(left + width - side, top, side, height, ink);
    }

    fn line(&self, start: Point, end: Point, ink: Colour) {
        let (mut x, mut y) = (i64::from(start.x), i64::from(start.y));
        let (end_x, end_y) = (i64::from(end.x), i64::from(end.y));
        let step_x = (end_x - x).signum();
        let step_y = (end_y - y).signum();
        let dx = (end_x - x).abs();
        let dy = -(end_y - y).abs();
        let mut error = dx + dy;
        loop {
            let x_dot = x as u32;
            let y_dot = y as u32;
            screen_rectangle(self.left + x_dot, self.top + y_dot,
                             STROKE.min(self.bounds.0 - x_dot), STROKE.min(self.bounds.1 - y_dot), ink);
            if x == end_x && y == end_y {
                break;
            }
            let twice = 2 * error;
            if twice >= dy {
                error += dy;
                x += step_x;
            }
            if twice <= dx {
                error += dx;
                y += step_y;
            }
        }
    }

    fn arrow(&self, start: Point, end: Point, ink: Colour) {
        self.line(start, end, ink);
        let (dx, dy) = (i64::from(end.x) - i64::from(start.x), i64::from(end.y) - i64::from(start.y));
        let distance = dx.abs().max(dy.abs());
        let length = (distance / 2).clamp(1, 10);
        let half = (length / 2).max(1);
        let base_x = i64::from(end.x) - dx * length / distance;
        let base_y = i64::from(end.y) - dy * length / distance;
        for side in [-1, 1] {
            let wing = Point {
                x: (base_x - side * dy * half / distance).clamp(0, i64::from(self.bounds.0 - 1)) as u32,
                y: (base_y + side * dx * half / distance).clamp(0, i64::from(self.bounds.1 - 1)) as u32,
            };
            self.line(wing, end, ink);
        }
    }
}
