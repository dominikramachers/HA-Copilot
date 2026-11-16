package plan

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
	"github.com/dominikramachers/ha-copilot/agent/internal/tools"
)

const (
	// PlanTTL ist länger als die Wartezeit auf die Freigabe in der App (10 Minuten).
	PlanTTL   = 15 * time.Minute
	maxPlans  = 32
	checkTime = 20 * time.Second
)

// Request und Response sind der Austausch mit dem Root-Helfer (eine Anfrage, eine Antwort).
type Request struct {
	Tool string `json:"tool"`
	Args Args   `json:"args"`
}

type Response struct {
	Output   string `json:"output"`
	ExitCode int    `json:"exit_code"`
	Error    string `json:"error,omitempty"`
}

// RootRunner führt eine Action mit root-Rechten aus (der Helfer stuft selbst erneut ein).
type RootRunner interface {
	Run(ctx context.Context, req Request) (Response, error)
	Available() bool
}

// Plan ist die Einstufung, wie sie an den Hub und von dort zur Freigabekarte geht.
type Plan struct {
	ID      string `json:"id"`
	Hash    string `json:"hash"`
	Tool    string `json:"tool"`
	Class   int    `json:"class"`
	Reason  string `json:"reason"`
	Summary string `json:"summary"`
	Command string `json:"command"`
	Runner  string `json:"runner"` // agent | root
	Preview string `json:"preview"`
	Undo    string `json:"undo"`
	Expires int64  `json:"expires"`
	Timeout int    `json:"timeout_s"`
	// Msgs sind die Texte mit Code (reason, summary, undo, preview), damit der Hub sie in der Sprache der Person zeigen kann.
	Msgs map[string]Msg `json:"msgs,omitempty"`
}

type stored struct {
	action  Action
	hash    string
	expires time.Time
}

// Manager hält die vorbereiteten Pläne (einmal verwendbar, nur im Arbeitsspeicher) und führt sie aus.
type Manager struct {
	Policy func() policy.Policy
	Root   RootRunner

	mu    sync.Mutex
	plans map[string]*stored
	write sync.Mutex // höchstens eine ändernde Ausführung gleichzeitig
	now   func() time.Time
}

func NewManager(load func() policy.Policy, root RootRunner) *Manager {
	return &Manager{Policy: load, Root: root, plans: map[string]*stored{}, now: time.Now}
}

type hashInput struct {
	Tool    string   `json:"tool"`
	Argv    []string `json:"argv"`
	Env     []string `json:"env"`
	Root    bool     `json:"root"`
	Timeout int      `json:"timeout_s"`
	Class   int      `json:"class"`
	Digest  string   `json:"digest,omitempty"`
}

// digest bindet bei Aufträgen ohne Befehlszeile (Datei schreiben) die Argumente in die Freigabe.
func (a Action) digest() string {
	if a.Tool != ToolFileWrite {
		return ""
	}
	raw, _ := json.Marshal(a.Args)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// Hash bindet die Freigabe an genau diesen Befehl.
func (a Action) Hash() string {
	raw, _ := json.Marshal(hashInput{a.Tool, a.Argv, a.Env, a.Root, int(a.Timeout.Seconds()), a.Class, a.digest()})
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// Allowed prüft die lokale Richtlinie gegen eine Einstufung. Gibt einen Satz zurück, warum nicht (leer = erlaubt).
func Allowed(p policy.Policy, a Action) string {
	switch {
	case !p.Operate:
		return "Changes by the AI are not allowed on this server (local policy ki_access=read)."
	case a.Class >= 3:
		return "Refused: " + a.Reason.Text
	case a.Class > p.MaxClass:
		return fmt.Sprintf("The local policy only allows changes up to class %d, this request is class %d (%s)", p.MaxClass, a.Class, a.Reason.Text)
	case a.Tool == ToolRun && !p.RunCommand:
		return "Free commands are switched off locally on this server (run_command=off)."
	case a.Root && !p.Root:
		return "Commands with root rights are switched off locally on this server (root=off)."
	case a.Tool == ToolFileWrite && !p.WriteAllowed(a.Args.text("path")):
		return fmt.Sprintf("Writing to %s is not allowed by the local policy (write_paths).", a.Args.text("path"))
	}
	return ""
}

func newID() string {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func (m *Manager) purge(now time.Time) {
	for id, s := range m.plans {
		if now.After(s.expires) {
			delete(m.plans, id)
		}
	}
	if len(m.plans) <= maxPlans {
		return
	}
	type kv struct {
		id string
		at time.Time
	}
	items := make([]kv, 0, len(m.plans))
	for id, s := range m.plans {
		items = append(items, kv{id, s.expires})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].at.Before(items[j].at) })
	for _, it := range items[:len(items)-maxPlans] {
		delete(m.plans, it.id)
	}
}

// Prepare stuft einen Auftrag ein und merkt ihn sich. Es wird nichts verändert.
func (m *Manager) Prepare(ctx context.Context, tool string, args Args) (Plan, error) {
	p := m.Policy()
	a, err := Classify(tool, args)
	if err != nil {
		return Plan{}, err
	}
	if why := Allowed(p, a); why != "" {
		return Plan{}, errors.New(why)
	}
	if a.Tool == ToolRun && len(a.Argv) > 0 {
		// Läuft das Programm überhaupt (nur Systemverzeichnisse)? Dann scheitert es nicht erst nach der Freigabe.
		if _, err := tools.LookPath(a.Argv[0]); err != nil {
			return Plan{}, err
		}
	}
	if a.Root && (m.Root == nil || !m.Root.Available()) {
		return Plan{}, errors.New("The root helper is not reachable on this server (check copilot-helper.service).")
	}
	preview, a, err := m.preview(ctx, a)
	if err != nil {
		return Plan{}, err
	}
	// Die Vorschau kann die Stufe anheben (z. B. würden zusätzlich Pakete entfernt): dann erneut gegen die Richtlinie prüfen.
	if why := Allowed(p, a); why != "" {
		return Plan{}, errors.New(why)
	}
	now := m.now()
	st := &stored{action: a, hash: a.Hash(), expires: now.Add(PlanTTL)}
	id := newID()
	m.mu.Lock()
	m.plans[id] = st
	m.purge(now)
	m.mu.Unlock()
	runner := "agent"
	if a.Root {
		runner = "root"
	}
	return Plan{
		ID: id, Hash: st.hash, Tool: a.Tool, Class: a.Class, Reason: a.Reason.Text, Summary: a.Summary.Text, Command: a.Command, Runner: runner,
		Preview: preview.FullText(), Undo: a.Undo.Text, Expires: st.expires.Unix(), Timeout: int(a.Timeout.Seconds()),
		Msgs: map[string]Msg{"reason": a.Reason, "summary": a.Summary, "undo": a.Undo, "preview": preview},
	}, nil
}

// Execute führt einen freigegebenen Plan aus. Jeder Plan gilt genau einmal; Ablauf, Hash und Richtlinie werden erneut geprüft.
func (m *Manager) Execute(ctx context.Context, planID, hash string) (string, error) {
	m.mu.Lock()
	st, ok := m.plans[planID]
	delete(m.plans, planID) // einmal verwendbar, auch bei Fehlern
	m.mu.Unlock()
	if !ok {
		return "", errors.New("This plan is unknown, expired or has already been executed. Please prepare it again.")
	}
	if m.now().After(st.expires) {
		return "", errors.New("The plan has expired. Please prepare it again.")
	}
	a := st.action
	if hash == "" || hash != st.hash || a.Hash() != st.hash {
		return "", errors.New("The approval does not match the prepared command.")
	}
	if why := Allowed(m.Policy(), a); why != "" {
		return "", errors.New(why)
	}
	if !m.write.TryLock() {
		return "", errors.New("Another change is already running on this server. Please try again later.")
	}
	defer m.write.Unlock()

	var out string
	var code int
	var runErr error
	if a.Root {
		if m.Root == nil || !m.Root.Available() {
			return "", errors.New("The root helper is not reachable.")
		}
		resp, err := m.Root.Run(ctx, Request{Tool: a.Tool, Args: a.Args})
		switch {
		case err != nil:
			return "", err
		case resp.Error != "":
			return "", errors.New(resp.Error)
		}
		out, code = resp.Output, resp.ExitCode
	} else {
		out, code, runErr = Exec(ctx, a)
		if runErr != nil && out == "" {
			return "", runErr
		}
	}
	return finish(ctx, a, out, code, runErr), nil
}

// finish hängt Exit-Code und Nachprüfung an und macht die Ausgabe sendefertig.
func finish(ctx context.Context, a Action, out string, code int, runErr error) string {
	var b strings.Builder
	b.WriteString(strings.TrimRight(out, "\n"))
	if runErr != nil {
		fmt.Fprintf(&b, "\n[Error: %v]", runErr)
	}
	status := "successful"
	if code != 0 || runErr != nil {
		status = fmt.Sprintf("failed (exit code %d)", code)
	}
	fmt.Fprintf(&b, "\n\n== Result: %s ==\n", status)
	if len(a.Check) > 0 {
		chk, _, err := tools.RunWith(ctx, tools.Opts{Timeout: checkTime}, a.Check[0], a.Check[1:]...)
		if err != nil && chk == "" {
			chk = err.Error()
		}
		b.WriteString("\n-- Check: " + strings.Join(a.Check, " ") + " --\n")
		b.WriteString(strings.TrimRight(chk, "\n") + "\n")
	}
	return tools.Clean(tools.Redact(b.String()))
}

// preview liefert den Text zur Freigabekarte (nur lesend). Bei Paketen wird ein Trockenlauf ausgewertet.
func (m *Manager) preview(ctx context.Context, a Action) (Msg, Action, error) {
	switch a.Tool {
	case ToolService:
		state, _, _ := tools.RunWith(ctx, tools.Opts{Timeout: 10 * time.Second}, "systemctl", "is-active", "--", a.Args.text("unit"))
		enabled, _, _ := tools.RunWith(ctx, tools.Opts{Timeout: 10 * time.Second}, "systemctl", "is-enabled", "--", a.Args.text("unit"))
		return T("svc.preview", "State now: {state}, at boot: {boot}", "state", oneLine(state, "unknown"), "boot", oneLine(enabled, "unknown")), a, nil
	case ToolPackage:
		if a.Args.text("action") == "update" {
			return T("pkg.preview.update", "Reloads the package lists; no packages are changed."), a, nil
		}
		sim := SimulationArgv(a)
		out, _, err := tools.RunWith(ctx, tools.Opts{Timeout: 90 * time.Second, Env: a.Env}, sim[0], sim[1:]...)
		if err != nil && out == "" {
			return Msg{}, a, fmt.Errorf("dry run not possible: %v", err)
		}
		text, removed := ParseSimulation(out)
		for _, r := range removed {
			if isProtectedPackage(r) {
				a.Class = 3
				a.Reason = T("pkg.reason.would_remove_protected", "This would also remove {package} (base system or login).", "package", r)
			}
		}
		if len(removed) > 0 && a.Class < 2 {
			a.Class = 2
			a.Reason = T("pkg.reason.also_removes", "Additional packages would be removed: {packages}", "packages", strings.Join(removed, ", "))
		}
		return text, a, nil
	case ToolFileWrite:
		return m.previewFileWrite(a)
	}
	if a.Class == 1 {
		return T("run.preview_read", "Read-only command; according to the classification it changes nothing."), a, nil
	}
	return T("run.preview", "The command is run exactly as shown above."), a, nil
}

func oneLine(s, def string) string {
	s = strings.TrimSpace(strings.SplitN(strings.TrimSpace(s), "\n", 2)[0])
	if s == "" {
		return def
	}
	return s
}

// ParseSimulation fasst die Ausgabe von „apt-get -s“ zusammen und nennt die zu entfernenden Pakete.
func ParseSimulation(out string) (Msg, []string) {
	var inst, remv []string
	var other []string
	for _, line := range strings.Split(out, "\n") {
		f := strings.Fields(line)
		if len(f) < 2 {
			continue
		}
		switch f[0] {
		case "Inst":
			inst = append(inst, f[1])
		case "Remv":
			remv = append(remv, f[1])
		case "Conf":
			// Konfiguration: nicht einzeln zeigen
		default:
			if strings.HasPrefix(line, "E:") || strings.HasPrefix(line, "W:") {
				other = append(other, line)
			}
		}
	}
	head := T("pkg.preview.sim", "Dry run: {inst} package(s) to install or upgrade, {remv} to remove.", "inst", strconv.Itoa(len(inst)), "remv", strconv.Itoa(len(remv)))
	list := func(code, format string, items []string) {
		if len(items) == 0 {
			return
		}
		more := 0
		if len(items) > 25 {
			more = len(items) - 25
			items = items[:25]
		}
		line := T(code, format, "packages", strings.Join(items, ", "))
		if more > 0 {
			line.Text += fmt.Sprintf(" … and %d more", more)
			line.Params["more"] = strconv.Itoa(more)
		}
		head.Then = append(head.Then, line)
	}
	list("pkg.preview.installs", "Install/upgrade: {packages}", inst)
	list("pkg.preview.removes", "Remove: {packages}", remv)
	for _, o := range other {
		head.Then = append(head.Then, Plain(o))
	}
	return head, remv
}

// Exec führt eine Action im aktuellen Prozess aus (ohne Shell). Der Helfer nutzt dieselbe Funktion als root.
func Exec(ctx context.Context, a Action) (string, int, error) {
	if len(a.Argv) == 0 {
		return "", -1, errors.New("no command")
	}
	return tools.RunWith(ctx, tools.Opts{Timeout: a.Timeout, Env: a.Env}, a.Argv[0], a.Argv[1:]...)
}
