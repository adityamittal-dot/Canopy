require "helper"

# Adds two numbers.
def add(a, b)
  if a > 0
    helper.scale(a, b)
  else
    a + b
  end
end

class Widget
  # Renders the widget.
  def render
    add(1, 2)
  end
end
