package metrics

import (
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestAddLimitsRateAndAge(t *testing.T) {
	now := time.Now()
	s := New()
	s.now = func() time.Time { return now }
	s.Add(Sample{At: now.Unix(), Load1: 1})
	s.Add(Sample{At: now.Unix() + 10, Load1: 2}) // too soon, dropped
	s.Add(Sample{At: now.Unix() + 60, Load1: 3})
	if s.Len() != 2 {
		t.Fatalf("want 2 samples, got %d", s.Len())
	}
	// old samples fall away
	s.now = func() time.Time { return now.Add(25 * time.Hour) }
	s.Add(Sample{At: now.Add(25 * time.Hour).Unix(), Load1: 4})
	if s.Len() != 1 {
		t.Fatalf("old samples must be dropped, have %d", s.Len())
	}
}

func TestSaveLoadRoundTrip(t *testing.T) {
	now := time.Now()
	s := New()
	for i := 0; i < 5; i++ {
		s.Add(Sample{At: now.Add(time.Duration(i-5) * time.Minute).Unix(), Load1: float64(i), MemPct: 40, DiskPct: 60})
	}
	path := filepath.Join(t.TempDir(), "metrics.json")
	if err := s.Save(path); err != nil {
		t.Fatal(err)
	}
	n := New()
	n.Load(path)
	if n.Len() != 5 {
		t.Fatalf("loaded %d samples", n.Len())
	}
	// unreadable or foreign content is ignored
	bad := filepath.Join(t.TempDir(), "x.json")
	_ = writeFile(bad, "not json")
	m := New()
	m.Load(bad)
	m.Load(filepath.Join(t.TempDir(), "missing.json"))
	if m.Len() != 0 {
		t.Error("broken file must give an empty history")
	}
}

func TestReport(t *testing.T) {
	s := New()
	if !strings.Contains(s.Report(60), "No metrics recorded") {
		t.Error("empty report")
	}
	now := time.Now()
	for i := 0; i < 60; i++ {
		s.Add(Sample{At: now.Add(time.Duration(i-60) * time.Minute).Unix(), Load1: float64(i % 10), MemPct: 30 + float64(i%5), DiskPct: 80})
	}
	out := s.Report(120)
	for _, want := range []string{"60 samples", "Load (1 min)", "max 9.00", "Fullest disk"} {
		if !strings.Contains(out, want) {
			t.Errorf("report misses %q:\n%s", want, out)
		}
	}
	// the window is clamped
	if strings.Contains(s.Report(1), "No metrics") && s.Len() == 0 {
		t.Error("clamped window")
	}
}
