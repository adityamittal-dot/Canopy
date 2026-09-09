use std::fmt;

/// Adds two numbers.
fn add(a: i32, b: i32) -> i32 {
    if a > 0 {
        return helper::scale(a, b);
    }
    a + b
}

struct Widget;

impl Widget {
    // Renders the widget.
    fn render(&self) {
        self.add(1, 2);
    }
}
