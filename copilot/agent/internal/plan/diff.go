package plan

import (
	"fmt"
	"strings"
)

type edit struct {
	op   byte // ' ', '+', '-'
	text string
}

// lineDiff vergleicht zwei Zeilenlisten (längste gemeinsame Teilfolge). Gleicher Anfang und gleiches Ende werden vorab abgezogen,
// so bleibt die Tabelle bei üblichen Änderungen klein.
func lineDiff(a, b []string) []edit {
	pre := 0
	for pre < len(a) && pre < len(b) && a[pre] == b[pre] {
		pre++
	}
	suf := 0
	for suf < len(a)-pre && suf < len(b)-pre && a[len(a)-1-suf] == b[len(b)-1-suf] {
		suf++
	}
	ma, mb := a[pre:len(a)-suf], b[pre:len(b)-suf]
	var out []edit
	for _, l := range a[:pre] {
		out = append(out, edit{' ', l})
	}
	// Tabelle der Länge der gemeinsamen Teilfolge
	n, m := len(ma), len(mb)
	table := make([][]int32, n+1)
	for i := range table {
		table[i] = make([]int32, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			switch {
			case ma[i] == mb[j]:
				table[i][j] = table[i+1][j+1] + 1
			case table[i+1][j] >= table[i][j+1]:
				table[i][j] = table[i+1][j]
			default:
				table[i][j] = table[i][j+1]
			}
		}
	}
	i, j := 0, 0
	for i < n && j < m {
		switch {
		case ma[i] == mb[j]:
			out = append(out, edit{' ', ma[i]})
			i++
			j++
		case table[i+1][j] >= table[i][j+1]:
			out = append(out, edit{'-', ma[i]})
			i++
		default:
			out = append(out, edit{'+', mb[j]})
			j++
		}
	}
	for ; i < n; i++ {
		out = append(out, edit{'-', ma[i]})
	}
	for ; j < m; j++ {
		out = append(out, edit{'+', mb[j]})
	}
	for _, l := range a[len(a)-suf:] {
		out = append(out, edit{' ', l})
	}
	return out
}

// UnifiedDiff zeigt die Unterschiede in der Art von „diff -u“ mit drei Zeilen Umgebung. Gibt den Text und die Zahl der
// hinzugefügten und entfernten Zeilen zurück.
func UnifiedDiff(oldText, newText string) (string, int, int) {
	split := func(s string) []string {
		if s == "" {
			return nil
		}
		return strings.Split(strings.TrimSuffix(s, "\n"), "\n")
	}
	edits := lineDiff(split(oldText), split(newText))
	const context = 3
	added, removed := 0, 0
	changed := make([]bool, len(edits))
	for i, e := range edits {
		if e.op != ' ' {
			changed[i] = true
			if e.op == '+' {
				added++
			} else {
				removed++
			}
		}
	}
	if added == 0 && removed == 0 {
		return "", 0, 0
	}
	keep := make([]bool, len(edits))
	for i := range edits {
		if changed[i] {
			for k := max(0, i-context); k <= min(len(edits)-1, i+context); k++ {
				keep[k] = true
			}
		}
	}
	var b strings.Builder
	oldLine, newLine := 1, 1
	for i := 0; i < len(edits); {
		if !keep[i] {
			if edits[i].op != '+' {
				oldLine++
			}
			if edits[i].op != '-' {
				newLine++
			}
			i++
			continue
		}
		start := i
		oldStart, newStart := oldLine, newLine
		oldCount, newCount := 0, 0
		for i < len(edits) && keep[i] {
			if edits[i].op != '+' {
				oldCount++
			}
			if edits[i].op != '-' {
				newCount++
			}
			i++
		}
		fmt.Fprintf(&b, "@@ -%d,%d +%d,%d @@\n", oldStart, oldCount, newStart, newCount)
		for _, e := range edits[start:i] {
			b.WriteString(string(e.op) + e.text + "\n")
		}
		oldLine, newLine = oldStart+oldCount, newStart+newCount
	}
	return strings.TrimRight(b.String(), "\n"), added, removed
}
