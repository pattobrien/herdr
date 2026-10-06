use std::io::{self, Write};

const BELL_CHUNK: [u8; 64] = [b'\x07'; 64];

pub(crate) fn write_terminal_bells<W: Write>(writer: &mut W, count: u16) -> io::Result<()> {
    let full_chunks = usize::from(count) / BELL_CHUNK.len();
    let remainder = usize::from(count) % BELL_CHUNK.len();
    for _ in 0..full_chunks {
        writer.write_all(&BELL_CHUNK)?;
    }
    writer.write_all(&BELL_CHUNK[..remainder])?;
    writer.flush()
}

pub(crate) fn write_window_title<W: Write>(writer: &mut W, title: Option<&str>) -> io::Result<()> {
    let title = title.unwrap_or("herdr");
    let safe_title = title
        .chars()
        .filter(|ch| !matches!(*ch, '\u{1b}' | '\u{7}' | '\u{9c}'))
        .collect::<String>();
    write!(writer, "\x1b]0;{safe_title}\x07")?;
    writer.flush()
}

/// Sets the host pointer shape through OSC 22; an empty shape restores the host default.
pub(crate) fn write_host_pointer_shape<W: Write>(writer: &mut W, shape: &str) -> io::Result<()> {
    let safe_shape = shape
        .chars()
        .filter(|ch| !ch.is_control())
        .collect::<String>();
    write!(writer, "\x1b]22;{safe_shape}\x1b\\")?;
    writer.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_exact_terminal_bell_count() {
        let mut output = Vec::new();

        write_terminal_bells(&mut output, 130).unwrap();

        assert_eq!(output, vec![b'\x07'; 130]);
    }

    #[test]
    fn window_title_strips_terminators_and_defaults_to_herdr() {
        let mut output = Vec::new();
        write_window_title(&mut output, Some("herdr\x1b api\u{7}\u{9c}")).unwrap();
        assert_eq!(output, b"\x1b]0;herdr api\x07");

        output.clear();
        write_window_title(&mut output, None).unwrap();
        assert_eq!(output, b"\x1b]0;herdr\x07");
    }

    #[test]
    fn host_pointer_shape_strips_controls_and_resets_with_empty_payload() {
        let mut output = Vec::new();
        write_host_pointer_shape(&mut output, "poin\x1bter\x07").unwrap();
        assert_eq!(output, b"\x1b]22;pointer\x1b\\");

        output.clear();
        write_host_pointer_shape(&mut output, "").unwrap();
        assert_eq!(output, b"\x1b]22;\x1b\\");
    }
}
