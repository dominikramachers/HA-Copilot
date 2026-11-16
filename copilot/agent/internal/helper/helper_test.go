package helper

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/plan"
	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
)

func start(t *testing.T, p func() policy.Policy, allow int) *Client {
	t.Helper()
	dir, err := os.MkdirTemp("", "hlp")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	sock := filepath.Join(dir, "h.sock")
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, Options{Socket: sock, AllowUID: allow, Policy: p}) }()
	t.Cleanup(func() { cancel(); <-done })
	for i := 0; i < 100; i++ {
		if _, err := os.Stat(sock); err == nil {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	return &Client{Socket: sock}
}

func operate() policy.Policy {
	return policy.Policy{Operate: true, MaxClass: 2, RunCommand: true, Root: true}
}

func TestHelperPingAndRun(t *testing.T) {
	c := start(t, operate, os.Getuid())
	if !c.Available() {
		t.Fatal("Helfer müsste antworten")
	}
	resp, err := c.Run(context.Background(), plan.Request{Tool: plan.ToolRun, Args: plan.Args{"argv": []any{"echo", "vom-helfer"}, "root": true}})
	if err != nil || resp.Error != "" || !strings.Contains(resp.Output, "vom-helfer") {
		t.Fatalf("%+v %v", resp, err)
	}
}

func TestHelperRechecksPolicyAndClass(t *testing.T) {
	cur := operate()
	c := start(t, func() policy.Policy { return cur }, os.Getuid())
	ctx := context.Background()
	// Stufe 3 lehnt der Helfer selbst dann ab, wenn der Agent sie schickt
	resp, _ := c.Run(ctx, plan.Request{Tool: plan.ToolRun, Args: plan.Args{"argv": []any{"reboot"}}})
	if !strings.Contains(resp.Error, "Abgelehnt") {
		t.Fatalf("Stufe 3: %+v", resp)
	}
	// ungültige Anfrage
	resp, _ = c.Run(ctx, plan.Request{Tool: "shell", Args: plan.Args{}})
	if resp.Error == "" {
		t.Fatal("unbekanntes Werkzeug muss scheitern")
	}
	// Richtlinie wird bei jeder Anfrage neu gelesen
	cur = policy.Default()
	resp, _ = c.Run(ctx, plan.Request{Tool: plan.ToolRun, Args: plan.Args{"argv": []any{"echo", "x"}}})
	if !strings.Contains(resp.Error, "nicht erlaubt") {
		t.Fatalf("nur lesen: %+v", resp)
	}
}

func TestHelperRejectsOtherUsers(t *testing.T) {
	if os.Getuid() == 0 {
		t.Skip("als root nicht prüfbar")
	}
	c := start(t, operate, os.Getuid()+1)
	resp, err := c.Run(context.Background(), plan.Request{Tool: plan.ToolRun, Args: plan.Args{"argv": []any{"echo", "x"}}})
	if err != nil || !strings.Contains(resp.Error, "verweigert") {
		t.Fatalf("fremder Benutzer: %+v %v", resp, err)
	}
	if c.Available() {
		t.Fatal("ein abgewiesener Benutzer darf den Helfer nicht als verfügbar sehen")
	}
}

func TestClientWithoutHelper(t *testing.T) {
	c := &Client{Socket: filepath.Join(t.TempDir(), "gibtsnicht.sock")}
	if c.Available() {
		t.Fatal("kein Helfer")
	}
	if _, err := c.Run(context.Background(), plan.Request{Tool: plan.ToolRun}); err == nil {
		t.Fatal("Fehler erwartet")
	}
}
