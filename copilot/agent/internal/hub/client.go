// Package hub ist die Verbindung des Agenten zum Hub im HA-Copilot-Add-on: Anmeldung („enroll“) und Dauerbetrieb („run“).
//
// Der Agent verbindet sich nur ausgehend. Er nimmt vom Hub ausschließlich „call“-Nachrichten für die festen lesenden Werkzeuge
// aus dem Paket tools an – und nur, wenn der Hub den Server als bestätigt („active“) meldet.
package hub

import (
	"context"
	"crypto/ecdsa"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"log/slog"
	"math/rand/v2"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"github.com/dominikramachers/ha-copilot/agent/internal/collect"
	"github.com/dominikramachers/ha-copilot/agent/internal/config"
	"github.com/dominikramachers/ha-copilot/agent/internal/plan"
	"github.com/dominikramachers/ha-copilot/agent/internal/tlsutil"
	"github.com/dominikramachers/ha-copilot/agent/internal/tools"
)

const (
	defaultInterval = 30 * time.Second
	minInterval     = 10 * time.Second
	maxInterval     = 120 * time.Second
	readLimit       = 256 * 1024
	maxParallel     = 2
	backoffStart    = 2 * time.Second
	backoffMax      = 60 * time.Second
)

func dialOptions(tlsConfig *tls.Config) *websocket.DialOptions {
	return &websocket.DialOptions{
		HTTPClient:      &http.Client{Transport: &http.Transport{TLSClientConfig: tlsConfig, TLSHandshakeTimeout: 15 * time.Second}},
		CompressionMode: websocket.CompressionDisabled,
	}
}

func url(hubAddr, path string) string { return "wss://" + hubAddr + path }

// message ist alles, was der Hub schicken kann.
type message struct {
	T        string          `json:"t"`
	ID       int             `json:"id"`
	Tool     string          `json:"tool"`
	Args     json.RawMessage `json:"args"`
	State    string          `json:"state"`
	Interval int             `json:"interval"`
	Msg      string          `json:"msg"`
	ServerID string          `json:"server_id"`
	PlanID   string          `json:"plan_id"`
	PlanHash string          `json:"plan_hash"`
	Cert     string          `json:"cert"`
	CA       string          `json:"ca"`
}

// EnrollOptions sind die Angaben der Anmeldung.
type EnrollOptions struct {
	Hub           string
	Key           string
	CAFingerprint string
	Name          string // Anzeigename; leer = Hostname
	Version       string
}

// Enroll meldet den Server mit einem Registrierungsschlüssel beim Hub an und speichert Schlüssel, Zertifikat und Zustand.
func Enroll(ctx context.Context, dir config.Dir, opt EnrollOptions) (string, error) {
	fingerprint, err := tlsutil.NormalizeFingerprint(opt.CAFingerprint)
	if err != nil {
		return "", err
	}
	if opt.Hub == "" || opt.Key == "" {
		return "", errors.New("Hub-Adresse und Registrierungsschlüssel sind nötig")
	}
	if err := dir.Ensure(); err != nil {
		return "", fmt.Errorf("Zustandsverzeichnis: %w", err)
	}
	if dir.Enrolled() {
		return "", errors.New("dieser Server ist schon angemeldet (zum Neuanmelden zuerst das Zustandsverzeichnis leeren oder das Skript mit --uninstall ausführen)")
	}
	host, _ := os.Hostname()
	name := opt.Name
	if name == "" {
		name = host
	}
	key, err := tlsutil.NewKey()
	if err != nil {
		return "", err
	}
	csr, err := tlsutil.CSRPEM(key, host)
	if err != nil {
		return "", err
	}

	ctx, cancel := context.WithTimeout(ctx, 40*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, url(opt.Hub, "/enroll"), dialOptions(tlsutil.Config(fingerprint, nil)))
	if err != nil {
		return "", fmt.Errorf("Verbindung zum Hub %s fehlgeschlagen: %w", opt.Hub, err)
	}
	defer conn.CloseNow()
	conn.SetReadLimit(readLimit)
	request, _ := json.Marshal(map[string]string{"t": "enroll", "key": opt.Key, "csr": csr, "hostname": name, "agent_version": opt.Version})
	if err := conn.Write(ctx, websocket.MessageText, request); err != nil {
		return "", fmt.Errorf("Senden fehlgeschlagen: %w", err)
	}
	_, data, err := conn.Read(ctx)
	if err != nil {
		return "", fmt.Errorf("keine Antwort vom Hub (Schlüssel abgelaufen oder verbraucht?): %w", err)
	}
	var reply message
	if err := json.Unmarshal(data, &reply); err != nil {
		return "", errors.New("unverständliche Antwort vom Hub")
	}
	switch reply.T {
	case "error":
		return "", fmt.Errorf("der Hub hat die Anmeldung abgelehnt: %s", reply.Msg)
	case "enrolled":
	default:
		return "", errors.New("unerwartete Antwort vom Hub")
	}
	if err := checkIssued(reply, fingerprint, &key.PublicKey); err != nil {
		return "", err
	}
	if err := dir.SaveKey(key); err != nil {
		return "", err
	}
	if err := dir.SaveCert(reply.Cert); err != nil {
		return "", err
	}
	if err := dir.Save(config.State{Hub: opt.Hub, CAFingerprint: fingerprint, ServerID: reply.ServerID, CAPEM: reply.CA}); err != nil {
		return "", err
	}
	_ = conn.Close(websocket.StatusNormalClosure, "")
	return reply.ServerID, nil
}

// checkIssued prüft, dass das Zertifikat zu unserem Schlüssel gehört und die CA die angeheftete ist.
func checkIssued(reply message, fingerprint string, public *ecdsa.PublicKey) error {
	block, _ := pem.Decode([]byte(reply.CA))
	if block == nil || tlsutil.Fingerprint(block.Bytes) != fingerprint {
		return errors.New("die CA in der Antwort passt nicht zum Fingerabdruck")
	}
	certBlock, _ := pem.Decode([]byte(reply.Cert))
	if certBlock == nil {
		return errors.New("kein Zertifikat in der Antwort")
	}
	cert, err := x509.ParseCertificate(certBlock.Bytes)
	if err != nil {
		return fmt.Errorf("Zertifikat unlesbar: %w", err)
	}
	if got, ok := cert.PublicKey.(*ecdsa.PublicKey); !ok || !got.Equal(public) {
		return errors.New("das Zertifikat gehört nicht zu meinem Schlüssel")
	}
	ca, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return err
	}
	if err := cert.CheckSignatureFrom(ca); err != nil {
		return fmt.Errorf("das Zertifikat ist nicht von der CA unterschrieben: %w", err)
	}
	return nil
}

// Agent ist der Dauerbetrieb.
type Agent struct {
	Dir     config.Dir
	Version string
	// Interval überschreibt den Takt (nur für Tests); 0 = vom Hub vorgegeben.
	Interval time.Duration
	// MinBackoff überschreibt den ersten Wartewert beim Wiederverbinden (nur für Tests).
	MinBackoff time.Duration
	// Changes führt ändernde Aufträge aus (Etappe 2). nil = der Agent kann nur lesen.
	Changes *plan.Manager
}

// Run verbindet sich, meldet sich regelmäßig und beantwortet Aufrufe, bis ctx endet. Verbindungsabbrüche werden mit wachsender
// Wartezeit wiederholt.
func (a *Agent) Run(ctx context.Context) error {
	state, err := a.Dir.Load()
	if err != nil {
		return err
	}
	cert, err := tlsutil.LoadClientCert(a.Dir.CertPath(), a.Dir.KeyPath())
	if err != nil {
		return fmt.Errorf("Zertifikat laden: %w", err)
	}
	tlsConfig := tlsutil.Config(state.CAFingerprint, cert)
	backoff := a.MinBackoff
	if backoff == 0 {
		backoff = backoffStart
	}
	wait := backoff
	for ctx.Err() == nil {
		started := time.Now()
		err := a.session(ctx, state, tlsConfig)
		if ctx.Err() != nil {
			return nil
		}
		slog.Warn("Verbindung zum Hub beendet", "fehler", err)
		if time.Since(started) > 30*time.Second {
			wait = backoff
		}
		sleep := wait/2 + time.Duration(rand.Int64N(int64(wait)))
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(sleep):
		}
		if wait *= 2; wait > backoffMax {
			wait = backoffMax
		}
	}
	return nil
}

// session ist eine Verbindung vom Aufbau bis zum Abbruch.
func (a *Agent) session(ctx context.Context, state config.State, tlsConfig *tls.Config) error {
	dialCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	conn, _, err := websocket.Dial(dialCtx, url(state.Hub, "/agent"), dialOptions(tlsConfig))
	cancel()
	if err != nil {
		return fmt.Errorf("verbinden: %w", err)
	}
	defer conn.CloseNow()
	conn.SetReadLimit(readLimit)
	slog.Info("mit dem Hub verbunden", "hub", state.Hub, "server", state.ServerID)

	ctx, stop := context.WithCancel(ctx)
	defer stop()

	var (
		mu       sync.Mutex
		active   bool
		interval = defaultInterval
	)
	if a.Interval > 0 {
		interval = a.Interval
	}
	collector := &collect.Collector{Version: a.Version, Annotate: a.annotate}
	send := func(v any) error {
		data, err := json.Marshal(v)
		if err != nil {
			return err
		}
		wctx, wcancel := context.WithTimeout(ctx, 15*time.Second)
		defer wcancel()
		return conn.Write(wctx, websocket.MessageText, data)
	}

	// Meldungen im Takt (der Takt kann der Hub ändern)
	beat := make(chan struct{}, 1)
	beat <- struct{}{}
	go func() {
		for {
			mu.Lock()
			d := interval
			mu.Unlock()
			select {
			case <-ctx.Done():
				return
			case <-time.After(d):
				select {
				case beat <- struct{}{}:
				default:
				}
			}
		}
	}()
	errs := make(chan error, 2)
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-beat:
				hb := collector.Collect(ctx)
				if err := send(hb); err != nil {
					errs <- fmt.Errorf("senden: %w", err)
					return
				}
			}
		}
	}()

	sem := make(chan struct{}, maxParallel)
	semWrite := make(chan struct{}, maxParallel)
	go func() {
		for {
			_, data, err := conn.Read(ctx)
			if err != nil {
				errs <- fmt.Errorf("lesen: %w", err)
				return
			}
			var m message
			if json.Unmarshal(data, &m) != nil {
				continue
			}
			switch m.T {
			case "ack":
				mu.Lock()
				now := m.State == "active"
				if now != active {
					slog.Info("Zustand beim Hub", "zustand", m.State)
				}
				active = now
				if a.Interval == 0 {
					if d := time.Duration(m.Interval) * time.Second; d >= minInterval && d <= maxInterval {
						interval = d
					}
				}
				mu.Unlock()
			case "prepare", "execute":
				mu.Lock()
				ok := active
				mu.Unlock()
				select {
				case semWrite <- struct{}{}:
					go func(m message) {
						defer func() { <-semWrite }()
						_ = send(a.change(ctx, m, ok))
					}(m)
				default:
					_ = send(map[string]any{"t": "result", "id": m.ID, "ok": false, "error": "Der Agent ist gerade ausgelastet."})
				}
			case "call":
				mu.Lock()
				ok := active
				mu.Unlock()
				select {
				case sem <- struct{}{}:
					go func(m message) {
						defer func() { <-sem }()
						_ = send(answer(ctx, m, ok))
					}(m)
				default:
					_ = send(map[string]any{"t": "result", "id": m.ID, "ok": false, "error": "Der Agent ist gerade ausgelastet."})
				}
			}
		}
	}()

	select {
	case err := <-errs:
		return err
	case <-ctx.Done():
		_ = conn.Close(websocket.StatusNormalClosure, "")
		return nil
	}
}

// answer führt einen Aufruf aus. Nur bestätigte Server antworten; nur bekannte Werkzeuge laufen.
func answer(ctx context.Context, m message, active bool) map[string]any {
	fail := func(text string) map[string]any {
		return map[string]any{"t": "result", "id": m.ID, "ok": false, "error": text}
	}
	if !active {
		return fail("Dieser Server ist noch nicht bestätigt.")
	}
	known := false
	for _, name := range tools.Names {
		if m.Tool == name {
			known = true
		}
	}
	if !known {
		return fail("Unbekanntes Werkzeug.")
	}
	args := tools.Args{}
	if len(m.Args) > 0 {
		if err := json.Unmarshal(m.Args, &args); err != nil {
			return fail("Die Argumente sind kein gültiges Objekt.")
		}
	}
	text, err := tools.Call(ctx, m.Tool, args)
	if err != nil {
		msg := err.Error()
		if len(msg) > 300 {
			msg = strings.ToValidUTF8(msg[:300], "")
		}
		return fail(msg)
	}
	return map[string]any{"t": "result", "id": m.ID, "ok": true, "text": text}
}

// annotate trägt ein, was die lokale Richtlinie erlaubt und ob der Root-Helfer antwortet.
func (a *Agent) annotate(hb *collect.Heartbeat) {
	if a.Changes == nil {
		return
	}
	p := a.Changes.Policy()
	hb.Operate, hb.MaxClass = p.Operate, p.MaxClass
	hb.Helper = a.Changes.Root != nil && a.Changes.Root.Available()
}

// change beantwortet „prepare“ (einstufen, nichts verändern) und „execute“ (einen freigegebenen Plan ausführen).
func (a *Agent) change(ctx context.Context, m message, active bool) map[string]any {
	fail := func(text string) map[string]any {
		if len(text) > 600 {
			text = strings.ToValidUTF8(text[:600], "") + "…"
		}
		return map[string]any{"t": "result", "id": m.ID, "ok": false, "error": text}
	}
	if !active {
		return fail("Dieser Server ist noch nicht bestätigt.")
	}
	if a.Changes == nil {
		return fail("Dieser Agent kann nur lesen.")
	}
	switch m.T {
	case "prepare":
		known := false
		for _, name := range plan.Names {
			if m.Tool == name {
				known = true
			}
		}
		if !known {
			return fail("Unbekanntes Werkzeug.")
		}
		args := plan.Args{}
		if len(m.Args) > 0 {
			if err := json.Unmarshal(m.Args, &args); err != nil {
				return fail("Die Argumente sind kein gültiges Objekt.")
			}
		}
		p, err := a.Changes.Prepare(ctx, m.Tool, args)
		if err != nil {
			return fail(err.Error())
		}
		raw, _ := json.Marshal(p)
		return map[string]any{"t": "result", "id": m.ID, "ok": true, "text": string(raw)}
	case "execute":
		// Eine begonnene Änderung wird nicht mittendrin abgebrochen, nur weil die Verbindung abreißt (das Zeitlimit des Plans gilt).
		text, err := a.Changes.Execute(context.WithoutCancel(ctx), m.PlanID, m.PlanHash)
		if err != nil {
			return fail(err.Error())
		}
		return map[string]any{"t": "result", "id": m.ID, "ok": true, "text": text}
	}
	return fail("Unbekannte Nachricht.")
}
