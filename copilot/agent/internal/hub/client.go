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
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"

	"github.com/dominikramachers/ha-copilot/agent/internal/collect"
	"github.com/dominikramachers/ha-copilot/agent/internal/config"
	"github.com/dominikramachers/ha-copilot/agent/internal/plan"
	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
	"github.com/dominikramachers/ha-copilot/agent/internal/tlsutil"
	"github.com/dominikramachers/ha-copilot/agent/internal/tools"
	"github.com/dominikramachers/ha-copilot/agent/internal/update"
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
	Offer    *update.Offer   `json:"offer"`
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
		return "", errors.New("hub address and registration key are required")
	}
	if err := dir.Ensure(); err != nil {
		return "", fmt.Errorf("state directory: %w", err)
	}
	if dir.Enrolled() {
		return "", errors.New("this server is already enrolled (to enroll again, empty the state directory first or run the script with --uninstall)")
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
		return "", fmt.Errorf("connection to the hub %s failed: %w", opt.Hub, err)
	}
	defer conn.CloseNow()
	conn.SetReadLimit(readLimit)
	request, _ := json.Marshal(map[string]string{"t": "enroll", "key": opt.Key, "csr": csr, "hostname": name, "agent_version": opt.Version})
	if err := conn.Write(ctx, websocket.MessageText, request); err != nil {
		return "", fmt.Errorf("sending failed: %w", err)
	}
	_, data, err := conn.Read(ctx)
	if err != nil {
		return "", fmt.Errorf("no answer from the hub (key expired or used up?): %w", err)
	}
	var reply message
	if err := json.Unmarshal(data, &reply); err != nil {
		return "", errors.New("unintelligible answer from the hub")
	}
	switch reply.T {
	case "error":
		return "", fmt.Errorf("the hub rejected the enrollment: %s", reply.Msg)
	case "enrolled":
	default:
		return "", errors.New("unexpected answer from the hub")
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
		return errors.New("the CA in the answer does not match the fingerprint")
	}
	certBlock, _ := pem.Decode([]byte(reply.Cert))
	if certBlock == nil {
		return errors.New("no certificate in the answer")
	}
	cert, err := x509.ParseCertificate(certBlock.Bytes)
	if err != nil {
		return fmt.Errorf("certificate not readable: %w", err)
	}
	if got, ok := cert.PublicKey.(*ecdsa.PublicKey); !ok || !got.Equal(public) {
		return errors.New("the certificate does not belong to my key")
	}
	ca, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return err
	}
	if err := cert.CheckSignatureFrom(ca); err != nil {
		return fmt.Errorf("the certificate is not signed by the CA: %w", err)
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
	Changes  *plan.Manager
	updating atomic.Bool
	confirm  sync.Once
	// PolicyDir ist das Verzeichnis der lokalen Richtlinie (dort liegen auch die Marken eines zurückgesetzten Updates).
	PolicyDir string
	// RenewBefore: so lange vor dem Ablauf wird das Zertifikat erneuert (0 = DefaultRenewBefore).
	RenewBefore time.Duration
}

// Run verbindet sich, meldet sich regelmäßig und beantwortet Aufrufe, bis ctx endet. Verbindungsabbrüche werden mit wachsender
// Wartezeit wiederholt.
func (a *Agent) Run(ctx context.Context) error {
	state, err := a.Dir.Load()
	if err != nil {
		return err
	}
	backoff := a.MinBackoff
	if backoff == 0 {
		backoff = backoffStart
	}
	wait := backoff
	for ctx.Err() == nil {
		started := time.Now()
		// Das Zertifikat wird bei jeder Verbindung neu geladen: nach einer Erneuerung gilt sofort das neue.
		cert, err := a.Dir.LoadKeyPair()
		if err != nil {
			return fmt.Errorf("loading certificate: %w", err)
		}
		err = a.session(ctx, state, tlsutil.Config(state.CAFingerprint, cert))
		if ctx.Err() != nil {
			return nil
		}
		if errors.Is(err, errRenewed) {
			wait = backoff
			continue
		}
		slog.Warn("connection to the hub ended", "error", err)
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
		return fmt.Errorf("connecting: %w", err)
	}
	defer conn.CloseNow()
	conn.SetReadLimit(readLimit)
	slog.Info("connected to the hub", "hub", state.Hub, "server", state.ServerID)

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
	renew := &renewal{}
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
				renew.start(a, send, false)
				hb := collector.Collect(ctx)
				if err := send(hb); err != nil {
					errs <- fmt.Errorf("sending: %w", err)
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
				errs <- fmt.Errorf("reading: %w", err)
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
					slog.Info("state at the hub", "state", m.State)
				}
				active = now
				if now && a.Changes != nil {
					// Die erste Antwort des Hubs nach einem Start bestätigt ein Update (der Helfer nimmt sonst die alte Fassung zurück).
					a.confirm.Do(func() { go a.confirmUpdate() })
					if m.Offer != nil && a.Changes.Policy().Update == policy.UpdateAuto {
						go func(o update.Offer) {
							if _, err := a.runUpdate(ctx, tlsConfig, state, o, true); err != nil {
								slog.Info("automatic update not applied", "reason", err)
							}
						}(*m.Offer)
					}
				}
				if a.Interval == 0 {
					if d := time.Duration(m.Interval) * time.Second; d >= minInterval && d <= maxInterval {
						interval = d
					}
				}
				mu.Unlock()
			case "renewed":
				if err := renew.finish(a, state, m); err != nil {
					if errors.Is(err, errRenewed) {
						errs <- err
						return
					}
					slog.Warn("certificate renewal failed", "error", err)
				}
			case "update":
				mu.Lock()
				ok := active
				mu.Unlock()
				go func(m message) {
					_ = send(a.updateNow(ctx, tlsConfig, state, m, ok))
				}(m)
			case "renew_now":
				renew.start(a, send, true)
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
					_ = send(map[string]any{"t": "result", "id": m.ID, "ok": false, "error": "The agent is busy at the moment."})
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
					_ = send(map[string]any{"t": "result", "id": m.ID, "ok": false, "error": "The agent is busy at the moment."})
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
		return fail("This server has not been confirmed yet.")
	}
	known := false
	for _, name := range tools.Names {
		if m.Tool == name {
			known = true
		}
	}
	if !known {
		return fail("Unknown tool.")
	}
	args := tools.Args{}
	if len(m.Args) > 0 {
		if err := json.Unmarshal(m.Args, &args); err != nil {
			return fail("The arguments are not a valid object.")
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
	if expires, err := CertExpiry(a.Dir); err == nil {
		hb.CertExpires = expires.Unix()
	}
	if a.Changes == nil {
		return
	}
	p := a.Changes.Policy()
	hb.Operate, hb.MaxClass, hb.UpdateMode = p.Operate, p.MaxClass, p.Update
	if f := update.ReadFailure(a.PolicyDir); f != nil {
		hb.UpdateFailed, hb.UpdateReason = f.Version, f.Reason
	}
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
		return fail("This server has not been confirmed yet.")
	}
	if a.Changes == nil {
		return fail("This agent can only read.")
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
			return fail("Unknown tool.")
		}
		args := plan.Args{}
		if len(m.Args) > 0 {
			if err := json.Unmarshal(m.Args, &args); err != nil {
				return fail("The arguments are not a valid object.")
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
	return fail("Unknown message.")
}

// confirmUpdate meldet dem Helfer, dass dieser Agent den Hub erreicht hat (macht ein anstehendes Update endgültig).
func (a *Agent) confirmUpdate() {
	if a.Changes == nil || a.Changes.Root == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_, _ = a.Changes.Root.Run(ctx, plan.Request{Tool: "agent_update_ok"})
}

// updateNow beantwortet die Aufforderung des Hubs, jetzt zu aktualisieren (Richtlinie update=manual oder auto). Die Antwort kommt
// sofort; das Laden und Einspielen läuft im Hintergrund, danach startet der Agent neu.
func (a *Agent) updateNow(ctx context.Context, tlsConfig *tls.Config, state config.State, m message, active bool) map[string]any {
	reply := func(ok bool, text string) map[string]any {
		key := "text"
		if !ok {
			key = "error"
		}
		return map[string]any{"t": "result", "id": m.ID, "ok": ok, key: text}
	}
	if !active {
		return reply(false, "This server has not been confirmed yet.")
	}
	if m.Offer == nil {
		return reply(false, "No update offer.")
	}
	if err := a.checkUpdate(*m.Offer, false); err != nil {
		return reply(false, err.Error())
	}
	go func(o update.Offer) {
		if text, err := a.runUpdate(context.WithoutCancel(ctx), tlsConfig, state, o, false); err != nil {
			slog.Warn("update failed", "error", err)
		} else {
			slog.Info(text)
		}
	}(*m.Offer)
	return reply(true, "Update started; the agent restarts when it is installed.")
}

// checkUpdate prüft vorab, was der Agent selbst wissen kann (Richtlinie, Fassung, frühere Fehlschläge).
func (a *Agent) checkUpdate(o update.Offer, auto bool) error {
	if a.Changes == nil || a.Changes.Root == nil || !a.Changes.Root.Available() {
		return errors.New("The root helper is not reachable on this server, updates need it.")
	}
	p := a.Changes.Policy()
	switch {
	case p.Update == policy.UpdateOff:
		return errors.New("Updates are switched off locally on this server (update=off).")
	case auto && p.Update != policy.UpdateAuto:
		return errors.New("Automatic updates are not enabled locally on this server (update=auto).")
	case !o.Valid():
		return errors.New("The update offer is invalid.")
	case !update.Newer(o.Version, a.Version):
		return fmt.Errorf("Version %s is not newer than the installed %s.", o.Version, a.Version)
	}
	if f := update.ReadFailure(a.PolicyDir); f != nil && f.Version == o.Version {
		return fmt.Errorf("Version %s was rolled back before and is not tried again.", o.Version)
	}
	return nil
}

// runUpdate lädt die angebotene Fassung, prüft sie und übergibt sie dem Root-Helfer.
func (a *Agent) runUpdate(ctx context.Context, tlsConfig *tls.Config, state config.State, o update.Offer, auto bool) (string, error) {
	if err := a.checkUpdate(o, auto); err != nil {
		return "", err
	}
	if !a.updating.CompareAndSwap(false, true) {
		return "", errors.New("an update is already running")
	}
	defer a.updating.Store(false)
	dir := filepath.Join(string(a.Dir), "update")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	dst := update.StagedPath(string(a.Dir))
	client := &http.Client{Transport: &http.Transport{TLSClientConfig: tlsConfig, TLSHandshakeTimeout: 15 * time.Second}}
	defer client.CloseIdleConnections()
	slog.Info("downloading update", "version", o.Version)
	if err := update.Download(ctx, client, "https://"+state.Hub+"/agent-update/"+runtime.GOARCH, dst, o); err != nil {
		return "", err
	}
	if err := update.SelfTest(ctx, dst, o.Version); err != nil {
		_ = os.Remove(dst)
		return "", err
	}
	resp, err := a.Changes.Root.Run(ctx, plan.Request{Tool: "agent_update", Args: plan.Args{
		"version": o.Version, "sha256": o.SHA256, "size": float64(o.Size), "sig": o.Sig, "auto": auto,
	}})
	if err != nil {
		return "", err
	}
	if resp.Error != "" {
		_ = os.Remove(dst)
		return "", errors.New(resp.Error)
	}
	return resp.Output, nil
}
