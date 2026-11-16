package tools

import (
	"context"
	"os"
	"strings"
	"testing"
)

func TestRedactRemovesSecrets(t *testing.T) {
	in := "password=hunter2 token: abc123def Authorization: Bearer xyz789 mysql://root:geheim@db/x\n" +
		"-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\nnormale Zeile"
	out := Redact(in)
	for _, leak := range []string{"hunter2", "abc123def", "xyz789", "geheim", "AAAA"} {
		if strings.Contains(out, leak) {
			t.Errorf("%q steht noch in der Ausgabe: %s", leak, out)
		}
	}
	if !strings.Contains(out, "normale Zeile") {
		t.Error("normaler Text darf nicht verloren gehen")
	}
}

func TestCleanStripsControlCharsAndLimitsLength(t *testing.T) {
	out := Clean("a\x00b\x1b[31mc\r\nd\xff")
	if strings.ContainsAny(out, "\x00\x1b\r\xff") {
		t.Fatalf("Steuerzeichen übrig: %q", out)
	}
	long := Clean(strings.Repeat("ä", MaxOutput))
	if len(long) > MaxOutput+100 || !strings.Contains(long, "gekürzt") {
		t.Fatalf("zu lang oder nicht gekürzt: %d", len(long))
	}
}

func TestCallRejectsUnknownToolsAndBadArguments(t *testing.T) {
	ctx := context.Background()
	for _, name := range []string{"", "rm", "system; id", "Service"} {
		if _, err := Call(ctx, name, nil); err == nil {
			t.Errorf("Werkzeug %q wurde ausgeführt", name)
		}
	}
	bad := []struct {
		tool string
		args Args
	}{
		{"service", Args{}},
		{"service", Args{"unit": "--help"}},
		{"service", Args{"unit": "a b"}},
		{"service", Args{"unit": "a;id"}},
		{"service", Args{"unit": "$(id)"}},
		{"service", Args{"unit": strings.Repeat("a", 101)}},
		{"journal", Args{"unit": "-f"}},
		{"journal", Args{"priority": "laut"}},
		{"journal", Args{"lines": "viele"}},
		{"journal", Args{"lines": 1.5}},
		{"journal", Args{"since_minutes": "x"}},
	}
	for _, c := range bad {
		if out, err := Call(ctx, c.tool, c.args); err == nil {
			t.Errorf("%s %v wurde ausgeführt: %q", c.tool, c.args, out)
		}
	}
}

func TestEveryNameIsHandled(t *testing.T) {
	want := []string{"system", "disks", "memory", "load", "processes", "services_failed", "service", "journal", "network", "updates", "users"}
	if strings.Join(Names, ",") != strings.Join(want, ",") {
		t.Fatalf("Werkzeugliste weicht vom Hub ab (READ_TOOLS in app/servers.py): %v", Names)
	}
	for _, name := range Names {
		_, err := Call(context.Background(), name, Args{"unit": "ssh.service"})
		if err != nil && err.Error() == "unbekanntes Werkzeug" {
			t.Errorf("%s ist nicht verdrahtet", name)
		}
	}
}

func TestArgsNumberClamps(t *testing.T) {
	a := Args{"n": 5000.0, "m": -3.0}
	if n, err := a.number("n", 50, 1, 200); err != nil || n != 200 {
		t.Fatalf("n=%d err=%v", n, err)
	}
	if n, err := a.number("m", 50, 1, 200); err != nil || n != 1 {
		t.Fatalf("m=%d err=%v", n, err)
	}
	if n, _ := a.number("fehlt", 50, 1, 200); n != 50 {
		t.Fatalf("Vorgabe: %d", n)
	}
}

func TestMemUsageAndOSRelease(t *testing.T) {
	total, pct, ok := MemUsage("MemTotal: 8192000 kB\nMemFree: 100 kB\nMemAvailable: 4096000 kB\n")
	if !ok || total != 8000 || pct < 49.9 || pct > 50.1 {
		t.Fatalf("%d %.2f %v", total, pct, ok)
	}
	if _, _, ok := MemUsage("MemTotal: 0 kB\n"); ok {
		t.Fatal("leere Angaben dürfen nicht gelten")
	}
	if got := OSRelease("NAME=\"Debian\"\nPRETTY_NAME=\"Debian GNU/Linux 12 (bookworm)\"\n"); got != "Debian GNU/Linux 12 (bookworm)" {
		t.Fatal(got)
	}
	if got := HumanDuration(90061); got != "1 Tage 1 Std 1 Min" {
		t.Fatal(got)
	}
}

func TestRunDoesNotUseAShell(t *testing.T) {
	out, err := Run(context.Background(), "echo", "$(id); rm -rf /")
	if err != nil || !strings.Contains(out, "$(id); rm -rf /") {
		t.Fatalf("Argumente müssen wörtlich ankommen: %q %v", out, err)
	}
	if _, err := Run(context.Background(), "gibt-es-nicht-xyz"); err == nil {
		t.Fatal("fehlendes Programm muss ein Fehler sein")
	}
	out, err = Run(context.Background(), "sh", "-c", "echo hi; exit 3")
	if err != nil || !strings.Contains(out, "Exit-Code 3") {
		t.Fatalf("Exit-Code gehört in die Ausgabe: %q %v", out, err)
	}
}

func TestLookPathOnlyUsesSystemDirectories(t *testing.T) {
	if p, err := LookPath("sh"); err != nil || !strings.HasSuffix(p, "/sh") {
		t.Fatalf("sh: %q %v", p, err)
	}
	if p, err := LookPath("/bin/sh"); err != nil || !strings.HasSuffix(p, "/sh") {
		t.Fatalf("/bin/sh: %q %v", p, err)
	}
	dir := t.TempDir()
	script := dir + "/evil"
	if err := os.WriteFile(script, []byte("#!/bin/sh\necho x\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{
		script, "./evil", "../bin/sh", "bin/sh", "/tmp/../tmp/x", "/usr/bin/../../tmp/x", "", " ", "..", ".", "/", "a\\b", "sh\x00",
		"/home/x/sh", "/opt/tool/sh", "/usr/bin/sub/sh",
	} {
		if p, err := LookPath(name); err == nil {
			t.Errorf("%q darf nicht gefunden werden, gefunden: %q", name, p)
		}
	}
}
