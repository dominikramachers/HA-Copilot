package plan

import "strings"

// Msg ist ein Text für die Freigabekarte. Der Agent schreibt nur Englisch (Text); Code und Parameter erlauben dem Hub, den
// Text in der Sprache der Person anzuzeigen (die Zuordnung steht im Hub, app/server_messages.py). Kennt der Hub den Code nicht
// (etwa bei einem neueren Agenten), zeigt er den englischen Text.
type Msg struct {
	Code   string            `json:"code,omitempty"`
	Text   string            `json:"text"`
	Params map[string]string `json:"params,omitempty"`
	// Then hängt weitere Nachrichten an (z. B. „Läuft als root.“ vor der eigentlichen Begründung, Listen unter einer Vorschau).
	Then []Msg `json:"then,omitempty"`
}

// T bildet eine Nachricht. In format stehen Platzhalter der Form {name}; kv sind Paare aus Name und Wert.
func T(code, format string, kv ...string) Msg {
	m := Msg{Code: code}
	if len(kv) >= 2 {
		m.Params = make(map[string]string, len(kv)/2)
	}
	text := format
	for i := 0; i+1 < len(kv); i += 2 {
		m.Params[kv[i]] = kv[i+1]
		text = strings.ReplaceAll(text, "{"+kv[i]+"}", kv[i+1])
	}
	m.Text = text
	return m
}

// Plain ist ein Text ohne Übersetzung (Befehle, Namen).
func Plain(text string) Msg { return Msg{Text: text} }

func (m Msg) String() string { return m.Text }

// FullText ist der englische Text samt angehängter Nachrichten (je Zeile eine).
func (m Msg) FullText() string {
	parts := []string{}
	if m.Text != "" {
		parts = append(parts, m.Text)
	}
	for _, t := range m.Then {
		if s := t.FullText(); s != "" {
			parts = append(parts, s)
		}
	}
	return strings.Join(parts, "\n")
}
