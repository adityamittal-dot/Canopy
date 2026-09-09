package sample

import "fmt"

// Add adds two ints.
func Add(a int, b int) int {
	if a > 0 {
		return helper.Scale(a, b)
	}
	return a + b
}

type Widget struct{}

// Render renders w.
func (w *Widget) Render() {
	w.Add(1, 2)
}
