<?php
require_once "helper.php";

// Adds two ints.
function add($a, $b) {
  if ($a > 0) {
    return helper::scale($a, $b);
  }
  return $a + $b;
}

class Widget {
  // Renders the widget.
  function render() {
    $this->add(1, 2);
    add(3, 4);
  }
}
