// Package metrics hält den Verlauf einiger Messwerte (Auslastung, Speicher, Datenträger) im Agenten, damit die KI nicht nur den
// Augenblick sieht, sondern auch „seit wann“. Der Verlauf liegt im Arbeitsspeicher und wird alle paar Minuten in das
// Zustandsverzeichnis geschrieben, damit ein Neustart (etwa nach einem Update) ihn nicht löscht.
package metrics

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	// Keep ist, wie weit der Verlauf zurückreicht.
	Keep = 24 * time.Hour
	// Step ist der Abstand zweier gespeicherter Werte.
	Step    = time.Minute
	maxRows = 24 * 60
)

// Sample ist ein Messpunkt.
type Sample struct {
	At      int64   `json:"t"` // Unix-Sekunden
	Load1   float64 `json:"l"`
	MemPct  float64 `json:"m"`
	DiskPct int     `json:"d"`
}

// Store ist der Verlauf.
type Store struct {
	mu      sync.Mutex
	samples []Sample
	since   time.Time
	now     func() time.Time
}

// New legt einen leeren Verlauf an.
func New() *Store { return &Store{now: time.Now, since: time.Now()} }

// Default ist der Verlauf des laufenden Agenten (gesetzt in main).
var Default = New()

// Add fügt einen Messpunkt an, höchstens einen je Minute; Älteres als 24 Stunden fällt weg.
func (s *Store) Add(x Sample) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if n := len(s.samples); n > 0 && x.At-s.samples[n-1].At < int64(Step.Seconds())-5 {
		return
	}
	s.samples = append(s.samples, x)
	cutoff := s.now().Add(-Keep).Unix()
	i := sort.Search(len(s.samples), func(i int) bool { return s.samples[i].At >= cutoff })
	if i > 0 {
		s.samples = append([]Sample(nil), s.samples[i:]...)
	}
	if len(s.samples) > maxRows {
		s.samples = append([]Sample(nil), s.samples[len(s.samples)-maxRows:]...)
	}
}

// Len ist die Zahl der Messpunkte.
func (s *Store) Len() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.samples)
}

// Save schreibt den Verlauf (atomar).
func (s *Store) Save(path string) error {
	s.mu.Lock()
	data, err := json.Marshal(s.samples)
	s.mu.Unlock()
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Load liest einen gespeicherten Verlauf; Unlesbares wird ignoriert.
func (s *Store) Load(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	var loaded []Sample
	if json.Unmarshal(data, &loaded) != nil {
		return
	}
	cutoff := s.now().Add(-Keep).Unix()
	kept := loaded[:0]
	for _, x := range loaded {
		if x.At >= cutoff && x.At <= s.now().Unix()+60 {
			kept = append(kept, x)
		}
	}
	sort.Slice(kept, func(i, j int) bool { return kept[i].At < kept[j].At })
	s.mu.Lock()
	s.samples = kept
	if len(kept) > 0 {
		s.since = time.Unix(kept[0].At, 0)
	}
	s.mu.Unlock()
}

type agg struct {
	min, max, sum float64
	n             int
}

func (a *agg) add(v float64) {
	if a.n == 0 || v < a.min {
		a.min = v
	}
	if a.n == 0 || v > a.max {
		a.max = v
	}
	a.sum += v
	a.n++
}

func (a agg) avg() float64 {
	if a.n == 0 {
		return 0
	}
	return a.sum / float64(a.n)
}

// Report fasst die letzten minutes Minuten zusammen: Summe über den Zeitraum und eine Tabelle mit höchstens 24 Zeilen.
func (s *Store) Report(minutes int) string {
	s.mu.Lock()
	all := append([]Sample(nil), s.samples...)
	since := s.since
	s.mu.Unlock()
	if minutes < 5 {
		minutes = 5
	}
	if minutes > 1440 {
		minutes = 1440
	}
	cutoff := s.now().Add(-time.Duration(minutes) * time.Minute).Unix()
	var rows []Sample
	for _, x := range all {
		if x.At >= cutoff {
			rows = append(rows, x)
		}
	}
	if len(rows) == 0 {
		return "No metrics recorded yet (the history starts when the agent starts and is kept for 24 hours).\n"
	}
	var load, mem, disk agg
	for _, x := range rows {
		load.add(x.Load1)
		mem.add(x.MemPct)
		disk.add(float64(x.DiskPct))
	}
	first, last := time.Unix(rows[0].At, 0).UTC(), time.Unix(rows[len(rows)-1].At, 0).UTC()
	var b strings.Builder
	fmt.Fprintf(&b, "Metrics from %s to %s UTC (%d samples, one per minute; history recorded since %s UTC)\n", first.Format("2006-01-02 15:04"), last.Format("2006-01-02 15:04"), len(rows), since.UTC().Format("2006-01-02 15:04"))
	fmt.Fprintf(&b, "Load (1 min):  min %.2f  avg %.2f  max %.2f\n", load.min, load.avg(), load.max)
	fmt.Fprintf(&b, "Memory used %%: min %.0f  avg %.0f  max %.0f\n", mem.min, mem.avg(), mem.max)
	fmt.Fprintf(&b, "Fullest disk %%: min %.0f  avg %.0f  max %.0f\n\n", disk.min, disk.avg(), disk.max)
	buckets := 24
	if len(rows) < buckets {
		buckets = len(rows)
	}
	b.WriteString("time (UTC)   load1(avg/max)  mem%(avg/max)  disk%(max)\n")
	for i := 0; i < buckets; i++ {
		lo, hi := i*len(rows)/buckets, (i+1)*len(rows)/buckets
		var l, m, d agg
		for _, x := range rows[lo:hi] {
			l.add(x.Load1)
			m.add(x.MemPct)
			d.add(float64(x.DiskPct))
		}
		fmt.Fprintf(&b, "%-12s %5.2f/%-8.2f  %3.0f/%-9.0f  %3.0f\n", time.Unix(rows[lo].At, 0).UTC().Format("01-02 15:04"), l.avg(), l.max, m.avg(), m.max, d.max)
	}
	return b.String()
}
