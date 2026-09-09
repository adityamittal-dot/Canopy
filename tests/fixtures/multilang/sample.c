#include <stdio.h>

// Adds two ints.
int add(int a, int b) {
  if (a > 0) {
    return helper_scale(a, b);
  }
  return a + b;
}
