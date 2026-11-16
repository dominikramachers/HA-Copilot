// Package helper ist der kleine Root-Teil des Agenten (Unterbefehl „helper“, eigene Systemd-Einheit copilot-helper.service).
//
// Der Agent selbst läuft ohne Rechte und stark eingeschränkt. Für Änderungen, die root brauchen (Dienste, apt), nimmt der Helfer über
// einen Unix-Socket genau eine Anfrage entgegen, stuft sie **selbst erneut ein**, prüft die lokale Richtlinie und führt sie aus.
// Der Helfer vertraut dem Agenten also nicht: Auch ein gekaperter Agent kann nur tun, was die Richtlinie und die Einstufung erlauben,
// nie Stufe 3 und nie etwas bei „ki_access=read“.
package helper

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/user"
	"strconv"
	"sync"
	"syscall"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/plan"
	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
)

const (
	// DefaultSocket liegt im Laufzeitverzeichnis, das die Systemd-Einheit des Helfers anlegt.
	DefaultSocket = "/run/copilot-agent/helper.sock"
	maxRequest    = 64 * 1024
	readTimeout   = 10 * time.Second
	pingTool      = "ping"
)

// Options steuern Serve.
type Options struct {
	Socket    string
	AllowUID  int    // nur dieser Benutzer (und root) darf anfragen; -1 = nur root
	GroupName string // Gruppe des Sockets (leer = unverändert)
	Policy    func() policy.Policy
}

// Serve nimmt Anfragen an, bis ctx endet.
func Serve(ctx context.Context, opt Options) error {
	_ = os.Remove(opt.Socket)
	ln, err := net.Listen("unix", opt.Socket)
	if err != nil {
		return err
	}
	defer ln.Close()
	mode := os.FileMode(0o600)
	if opt.GroupName != "" {
		if g, err := user.LookupGroup(opt.GroupName); err == nil {
			if gid, err := strconv.Atoi(g.Gid); err == nil && os.Chown(opt.Socket, -1, gid) == nil {
				mode = 0o660
			}
		}
	}
	if err := os.Chmod(opt.Socket, mode); err != nil {
		return err
	}
	go func() {
		<-ctx.Done()
		ln.Close()
	}()
	s := &server{opt: opt}
	for {
		conn, err := ln.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		go s.handle(ctx, conn.(*net.UnixConn))
	}
}

type server struct {
	opt  Options
	busy sync.Mutex
}

func peerUID(c *net.UnixConn) (int, error) {
	raw, err := c.SyscallConn()
	if err != nil {
		return -1, err
	}
	uid := -1
	var cerr error
	err = raw.Control(func(fd uintptr) {
		cred, e := syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
		if e != nil {
			cerr = e
			return
		}
		uid = int(cred.Uid)
	})
	if err != nil {
		return -1, err
	}
	return uid, cerr
}

func reply(c net.Conn, r plan.Response) {
	_ = json.NewEncoder(c).Encode(r)
}

func (s *server) handle(ctx context.Context, c *net.UnixConn) {
	defer c.Close()
	uid, err := peerUID(c)
	if err != nil || (uid != 0 && uid != s.opt.AllowUID) {
		reply(c, plan.Response{ExitCode: -1, Error: "Zugriff verweigert"})
		return
	}
	_ = c.SetReadDeadline(time.Now().Add(readTimeout))
	line, err := bufio.NewReaderSize(io.LimitReader(c, maxRequest), 4096).ReadBytes('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		reply(c, plan.Response{ExitCode: -1, Error: "Anfrage nicht lesbar"})
		return
	}
	_ = c.SetReadDeadline(time.Time{})
	var req plan.Request
	if json.Unmarshal(line, &req) != nil {
		reply(c, plan.Response{ExitCode: -1, Error: "Anfrage ungültig"})
		return
	}
	if req.Tool == pingTool {
		reply(c, plan.Response{Output: "pong"})
		return
	}
	a, err := plan.Classify(req.Tool, req.Args)
	if err != nil {
		reply(c, plan.Response{ExitCode: -1, Error: err.Error()})
		return
	}
	// Die Richtlinie wird bei jeder Anfrage neu gelesen: eine Änderung der Datei wirkt sofort.
	if why := plan.Allowed(s.opt.Policy(), a); why != "" {
		reply(c, plan.Response{ExitCode: -1, Error: why})
		return
	}
	if !s.busy.TryLock() {
		reply(c, plan.Response{ExitCode: -1, Error: "Der Helfer führt gerade schon eine Änderung aus."})
		return
	}
	defer s.busy.Unlock()
	out, code, runErr := plan.Exec(ctx, a)
	r := plan.Response{Output: out, ExitCode: code}
	if runErr != nil {
		r.Output += fmt.Sprintf("\n[Fehler: %v]", runErr)
		if out == "" {
			r.Error = runErr.Error()
		}
	}
	reply(c, r)
}

// Client spricht mit dem Helfer (läuft im Agenten).
type Client struct {
	Socket string
}

func (c *Client) roundTrip(ctx context.Context, req plan.Request, limit time.Duration) (plan.Response, error) {
	d := net.Dialer{Timeout: 3 * time.Second}
	conn, err := d.DialContext(ctx, "unix", c.Socket)
	if err != nil {
		return plan.Response{}, fmt.Errorf("Der Root-Helfer ist nicht erreichbar: %w", err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(limit))
	stop := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer stop()
	if err := json.NewEncoder(conn).Encode(req); err != nil {
		return plan.Response{}, err
	}
	var resp plan.Response
	if err := json.NewDecoder(io.LimitReader(conn, 4*1024*1024)).Decode(&resp); err != nil {
		return plan.Response{}, fmt.Errorf("Antwort des Root-Helfers nicht lesbar: %w", err)
	}
	return resp, nil
}

// Run führt eine Anfrage aus. Die Wartezeit reicht für das längste erlaubte Zeitlimit plus Reserve.
func (c *Client) Run(ctx context.Context, req plan.Request) (plan.Response, error) {
	return c.roundTrip(ctx, req, 17*time.Minute)
}

// Available prüft mit einem Ping, ob der Helfer antwortet.
func (c *Client) Available() bool {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	r, err := c.roundTrip(ctx, plan.Request{Tool: pingTool}, 2*time.Second)
	return err == nil && r.Output == "pong"
}
