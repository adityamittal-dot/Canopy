using System;

class Widget {
  /// Adds two ints.
  int Add(int a, int b) {
    if (a > 0) {
      return Helper.Scale(a, b);
    }
    return a + b;
  }

  // Renders the widget.
  void Render() {
    this.Add(1, 2);
  }
}
