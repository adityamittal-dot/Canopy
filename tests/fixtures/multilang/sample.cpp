#include <iostream>

class Widget {
  public:
  // Adds two ints.
  int add(int a, int b) {
    if (a > 0) {
      return helper::scale(a, b);
    }
    return a + b;
  }

  // Renders the widget.
  void render() {
    this->add(1, 2);
  }
};
