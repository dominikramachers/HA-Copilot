package plan

import (
	"strings"
	"testing"
)

func TestUnifiedDiff(t *testing.T) {
	old := "a\nb\nc\nd\ne\n"
	next := "a\nb\nX\nd\ne\nf\n"
	text, added, removed := UnifiedDiff(old, next)
	if added != 2 || removed != 1 {
		t.Fatalf("added=%d removed=%d, want 2/1\n%s", added, removed, text)
	}
	for _, want := range []string{"-c", "+X", "+f"} {
		if !strings.Contains(text, want) {
			t.Errorf("diff misses %q:\n%s", want, text)
		}
	}
	if same, a, r := UnifiedDiff(old, old); a != 0 || r != 0 || strings.Contains(same, "\n-") {
		t.Errorf("identical texts must give an empty diff, got %q (%d/%d)", same, a, r)
	}
	if _, a, r := UnifiedDiff("", "one\ntwo\n"); a != 2 || r != 0 {
		t.Errorf("new file: added=%d removed=%d", a, r)
	}
	if _, a, r := UnifiedDiff("one\ntwo\n", ""); a != 0 || r != 2 {
		t.Errorf("emptied file: added=%d removed=%d", a, r)
	}
}

func TestUnifiedDiffLarge(t *testing.T) {
	var a, b []string
	for i := 0; i < 3000; i++ {
		a = append(a, "line "+strings.Repeat("x", i%7))
		b = append(b, "line "+strings.Repeat("x", i%7))
	}
	b[1500] = "changed"
	_, added, removed := UnifiedDiff(strings.Join(a, "\n")+"\n", strings.Join(b, "\n")+"\n")
	if added != 1 || removed != 1 {
		t.Fatalf("added=%d removed=%d, want 1/1", added, removed)
	}
}
